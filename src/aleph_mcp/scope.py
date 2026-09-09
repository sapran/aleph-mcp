"""The one home for collection scope: what a call is scoped to, and how that reaches Aleph.

Aleph answers an unscoped search *successfully*, so a caller that meant one collection and
failed to say so receives another collection's rows with no error anywhere. That is the
data-integrity failure this module exists to prevent, and it is why the scope is required
rather than defaulted, why `"*"` is the only way to opt out of it, and why a value that
names no collection is refused rather than passed on.

The three halves are separated because each fails differently:

*Parse* is pure and refuses without I/O. That is load-bearing rather than tidy —
`openspec/specs/mcp-tool-surface` promises that a refused call costs no collection lookup,
so a scope naming nothing must be reported before anything is sent. It is also what lets
those refusals be tested without a mocked upstream.

*Resolve* owns the one upstream request the scope needs, the `foreign_id` listing, and the
cache that stops a session paying for it twice. It reaches HTTP through an injected
callable, so this module knows what a collection scope is and nothing about transport.

*Render* is why a resolved scope is a type rather than a list of strings. Three call sites
used to re-derive how a scope becomes a query parameter, in two different wire spellings,
and a fourth reported it back to the caller. Getting one of them wrong is silent: the
search still succeeds, over a scope nobody asked for.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from .echo import COLLECTION_ECHO, render

# Query parameters this module emits. Deliberately narrower than `client.Query` — every
# collection filter value is a numeric id, already a string — so the module that owns the
# scope needs no import from the module that owns HTTP.
Filters = list[tuple[str, str]]

# Matched with `fullmatch`, as in readonly.py — no anchors, so the two agree by
# construction. An anchored `$` here is what previously let a trailing newline through.
_COLLECTION_ID = re.compile(r"[0-9]+")

# The only way to ask for an unscoped search. Deliberately not a natural-language word: a
# caller that types it has chosen to search every readable collection, where a caller that
# omits the argument entirely has chosen nothing and is refused. See
# openspec/specs/mcp-tool-surface — an unscoped search returned in answer to a scoped
# question contaminates a product with another collection's rows, silently.
ALL_COLLECTIONS: Final = "*"

# How many collections one call may name. Each uncached foreign id is a whole upstream
# request with its own retry budget; this is what stops one tool call from multiplying that
# budget by the length of a caller-supplied list. Ten is well past the one or two a real
# session uses, and far short of an instance's collection count.
MAX_SCOPE_COLLECTIONS = 10

# The two wire spellings, named once. Aleph's search and listing endpoints take
# `filter:collection_id`; /api/2/match takes `collection_ids`. Both are Aleph's vocabulary,
# not this server's — see the one-vocabulary requirement in openspec/specs/mcp-tool-surface,
# which is why neither name reaches the tool surface.
_SEARCH_FILTER: Final = "filter:collection_id"
_MATCH_FILTER: Final = "collection_ids"


def check_collection_id(value: object) -> str:
    text = str(value)
    if not _COLLECTION_ID.fullmatch(text):
        raise ValueError(
            # `value` is caller input on every path but one: the id read out of a
            # foreign_id lookup is upstream text, so it is bounded under the shared rule
            # in echo.py — an unbounded echo is a write primitive into the model's
            # context. `!r` additionally escapes control characters, which is why
            # COLLECTION_ECHO does not strip them itself.
            f"invalid collection: expected a numeric collection id "
            f"(got {render(text, COLLECTION_ECHO)!r}). "
            "A foreign_id is accepted directly and resolved for you; this error means the "
            "value is neither."
        )
    return text


def _is_numeric_form(text: str) -> bool:
    """True when the value is digits and whitespace only — numeric *intent*.

    Read loosely on purpose, so that `"42\\n"` is understood as a numeric id and refused by
    the validator, rather than falling through to the foreign_id branch and quietly
    resolving to nothing. The corollary, stated because it is surprising: a value of only
    digits is ALWAYS read as a numeric id, so a collection whose foreign_id is all digits
    cannot be addressed by that foreign_id — pass its numeric id.
    """
    return not text.strip("0123456789 \t\r\n")


def parse_collection(collection: str | int) -> str:
    """Return the spelling a single-collection argument names, or refuse it.

    Pure, and every refusal here precedes any request: this is the half of the promise
    that a refused call costs no lookup.
    """
    text = str(collection)
    # Refused before the cache and before any request. An empty or blank value names
    # no collection, and Aleph does not treat it as naming none: `sanitize_text`
    # returns None for it, the filter set comes out empty, and `field_filter_query`
    # emits `match_all` — so the listing answers with the first collection this key
    # can read and `limit=1` takes it. That is a silently misdirected search, which is
    # the exact failure this argument exists to prevent.
    if not text.strip():
        raise ValueError(
            "collection must not be empty: pass a numeric collection id, a foreign_id, "
            f"or {ALL_COLLECTIONS!r} to search every readable collection"
        )
    if text == ALL_COLLECTIONS:
        raise ValueError(
            f"this tool addresses exactly one collection, so {ALL_COLLECTIONS!r} is not "
            "meaningful here; it is the all-collections literal for search_entities and "
            "match_entity only. Pass one collection id or foreign_id."
        )
    return text


def parse_scope(collection: str | int | list[str | int]) -> tuple[str, ...] | None:
    """Return the spellings a scope names, deduplicated in order — or `None` for `"*"`.

    Pure. Accepts the literal `"*"`, a single id in either form, or a list of them. A
    caller that omits the argument never reaches here — the tool signature refuses first,
    which is the point: see the required-scope requirement in the spec.

    Each element is parsed later, by `parse_collection` as it is resolved, so a blank
    element is refused at the position the caller wrote it rather than ahead of the
    element before it.
    """
    # A scalar, either spelling: a model handed a numeric id often sends the JSON
    # number rather than the string, and rejecting that would spend a turn on syntax.
    if not isinstance(collection, list):
        if collection == ALL_COLLECTIONS:
            return None
        return (str(collection),)

    if not collection:
        raise ValueError(
            "collection must name at least one collection, or the literal '*' to search "
            "every readable collection"
        )
    if ALL_COLLECTIONS in collection:
        raise ValueError(
            "collection='*' searches every readable collection and cannot be combined "
            "with named collections; pass either '*' or the ids you want"
        )
    # Deduplicated preserving order, and bounded. Each uncached foreign id is a whole
    # upstream request with its own retry budget, so an unbounded list would let one
    # tool call multiply that budget — the same amplification the per-request budget
    # and the shrink loop's deadline both exist to prevent.
    # Stringified first, so a list mixing 874 and "874" dedups as one spelling.
    unique = tuple(dict.fromkeys(str(c) for c in collection))
    if len(unique) > MAX_SCOPE_COLLECTIONS:
        raise ValueError(
            f"collection may name at most {MAX_SCOPE_COLLECTIONS} collections in one "
            f"call (got {len(unique)}). Each one may cost a lookup, so query the slices "
            "separately, or pass '*' and filter the hits by collection_id."
        )
    return unique


@dataclass(frozen=True, slots=True)
class ResolvedCollection:
    """One collection, resolved to the numeric id Aleph addresses it by.

    A type rather than a bare string, so the id a path interpolates and the filter a
    listing carries come from the same place and neither is spelled at a call site.
    """

    id: str

    def filters(self) -> Filters:
        """The filter that narrows a listing to this collection.

        One spelling, two endpoints: /api/2/entities and /api/2/entitysets both take it.
        """
        return [(_SEARCH_FILTER, self.id)]


@dataclass(frozen=True, slots=True)
class CollectionScope:
    """What a search is scoped to: named collections, or every readable one.

    `collections is None` is the resolved form of `"*"`, and is not the same as an empty
    tuple — which cannot occur, because a scope naming nothing is refused at parse time.
    The distinction is the point: an empty filter list and "every collection" produce the
    same wire request, so the sentinel is what lets the reply say which one was meant.
    """

    collections: tuple[ResolvedCollection, ...] | None

    @property
    def is_every_collection(self) -> bool:
        """Whether this scope is the deliberate cross-collection search."""
        return self.collections is None

    def search_filters(self) -> Filters:
        """`filter:collection_id`, one per collection — /api/2/entities.

        A list ORs within the key, which is Aleph's filter semantics. Empty for `"*"`:
        omitting the filter is how Aleph is asked for every collection the key can read.
        """
        if self.collections is None:
            return []
        return [f for collection in self.collections for f in collection.filters()]

    def match_filters(self) -> Filters:
        """`collection_ids`, one per collection — /api/2/match.

        Aleph's match endpoint spells the same idea differently, and omitting it is its
        all-collections behaviour — `match_query` adds a terms filter only for a non-empty
        list, and the authorisation filter still bounds the result to what this key may
        read. The wire name stays here and does not reach the tool surface — see the
        one-vocabulary requirement in openspec/specs/mcp-tool-surface.
        """
        if self.collections is None:
            return []
        return [(_MATCH_FILTER, collection.id) for collection in self.collections]

    def reported(self) -> str | list[str]:
        """What the reply carries under `searched.collection`.

        The resolved ids, so a caller can tell "no matches" from "matched nothing in a
        scope I did not choose" — or the literal, which is the one non-list value that key
        takes.
        """
        if self.collections is None:
            return ALL_COLLECTIONS
        return [collection.id for collection in self.collections]


# The one upstream request the scope needs: the collection listing filtered by foreign_id,
# taking the foreign_id and the calling tool's name, and returning the decoded payload.
# Injected, so this module owns no transport and its refusals need no mocked upstream.
ForeignIdLookup = Callable[[str, str], Awaitable[dict[str, Any]]]


class CollectionResolver:
    """Resolves collection spellings to numeric ids, and remembers what it resolved."""

    def __init__(
        self,
        *,
        lookup: ForeignIdLookup,
        timeout_secs: Callable[[], float],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._lookup = lookup
        # Both are read at call time rather than captured, so a test that adjusts the
        # settings or advances a fake clock after this object is built still governs the
        # deadline below — the same indirection the shrink loop uses one level up.
        self._timeout_secs = timeout_secs
        self._monotonic = monotonic
        # foreign_id -> numeric collection id, for the process lifetime. See
        # `resolve_one` for why this never needs invalidating.
        self._cache: dict[str, str] = {}

    @property
    def cached(self) -> Mapping[str, str]:
        """What has been resolved so far. A read-only view: nothing may seed this."""
        return MappingProxyType(self._cache)

    async def resolve_one(self, collection: str | int, *, context: str) -> ResolvedCollection:
        """Resolve a numeric id or a foreign_id to the one collection it names.

        The numeric branch interpolates into a path, so it goes through the shared
        validator rather than trusting the branch test — see `_is_numeric_form` for why
        that test is deliberately loose.

        A foreign_id is left free-form on purpose: it becomes a url-encoded query
        parameter and cannot escape the path, and foreign ids are not constrained to any
        charset.

        `context` names the calling tool so a failed lookup is reported against the tool
        the caller actually invoked, rather than against `get_collection`.
        """
        text = parse_collection(collection)
        if _is_numeric_form(text):
            return ResolvedCollection(check_collection_id(text))

        cached = self._cache.get(text)
        if cached is not None:
            return ResolvedCollection(cached)

        listing = await self._lookup(text, context)
        results = listing.get("results") or []
        hit = results[0] if results and isinstance(results[0], dict) else None
        # Tie the answer back to the question. Without this the resolver trusts that the
        # upstream applied the filter it was given, and any leniency — a dropped filter, a
        # loose match, a redirect answered by a different listing — resolves to a
        # plausible id for a collection nobody named, then caches it for the process
        # lifetime. A non-dict row is checked in the same breath because the lookup wraps
        # a non-dict JSON body as `{"results": <body>}`, and `.get` on a str would raise
        # AttributeError, which no tool's `except ValueError` translates.
        if hit is None or hit.get("foreign_id") != text:
            raise ValueError(
                f"no collection with foreign_id {text!r} is readable with this API key; "
                "call list_collections to see what is available"
            )
        resolved = check_collection_id(hit.get("id"))
        # A collection's numeric id never changes, so this needs no invalidation. Cached for
        # the process lifetime beside the instance model: a session works one or two
        # collections and would otherwise pay a lookup on every scoped call. Only a verified
        # hit is cached; a failure is never stored, so a bogus id cannot grow the map.
        self._cache[text] = resolved
        return ResolvedCollection(resolved)

    async def resolve_scope(
        self, collection: str | int | list[str | int], *, context: str
    ) -> CollectionScope:
        """Resolve `"*"`, one collection, or a list of them into a `CollectionScope`.

        Every refusal `parse_scope` makes is local and precedes any request, so a scope
        that names nothing costs nothing.
        """
        spellings = parse_scope(collection)
        if spellings is None:
            return CollectionScope(None)
        # One resolution phase, one deadline, mirroring the shrink loop: each request is
        # bounded on its own budget, and N of them in sequence would otherwise multiply
        # that budget by N before the search is even sent.
        budget = self._timeout_secs()
        deadline = self._monotonic() + budget
        resolved: list[ResolvedCollection] = []
        for item in spellings:
            if resolved and self._monotonic() >= deadline:
                raise ValueError(
                    f"resolving the collection scope exceeded this call's "
                    f"{budget}s budget after {len(resolved)} of "
                    f"{len(spellings)} collections. Pass numeric ids, which need no lookup, or "
                    "query fewer collections per call."
                )
            resolved.append(await self.resolve_one(item, context=context))
        # Deduplicated again, on the resolved ids: a numeric id and a foreign_id naming the
        # same collection are two distinct spellings that collapse to one id, and emitting
        # `filter:collection_id` twice for it would contradict what `searched.collection`
        # reports and what the one-filter-per-id contract says.
        return CollectionScope(tuple(dict.fromkeys(resolved)))
