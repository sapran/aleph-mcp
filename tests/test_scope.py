"""The collection-scope module on its own: parse, resolve, cache, render.

Not one `respx` route in this file, and that is the point rather than an economy. The
scope's refusals are the half of `openspec/specs/mcp-tool-surface` that promises a refused
call costs no collection lookup, so a refusal that needs a mocked upstream to be tested is
a refusal that has already sent something. The lookup here is an in-process callable, and
most cases pass one that fails the test if it is called at all.

`tests/test_collection_scope.py` keeps the end-to-end contract — what reaches the wire and
what the reply says. This file pins the module those tests run through.
"""

from typing import Any

import pytest

from aleph_mcp.errors import Refusal
from aleph_mcp.scope import (
    ALL_COLLECTIONS,
    MAX_SCOPE_COLLECTIONS,
    CollectionResolver,
    CollectionScope,
    ResolvedCollection,
    parse_collection,
    parse_scope,
)

# 122 characters, carrying a control character and a double quote. Stands in for the one
# path where a collection id is upstream text rather than caller text: the `id` read out of
# a foreign_id lookup.
UPSTREAM_ID = "a" * 60 + "\x1b" + '"' + "b" * 60


async def _refuse_to_look_up(foreign_id: str, context: str) -> dict[str, Any]:
    raise AssertionError(
        f"a local refusal cost an upstream lookup: {foreign_id!r} for {context}. Every "
        "parse-level refusal must precede any request -- see the required-scope "
        "requirement in openspec/specs/mcp-tool-surface."
    )


class FakeUpstream:
    """The one request the resolver makes, answered in process.

    `ids` maps a foreign_id to the numeric id a well-behaved instance would return.
    `answer` replaces the whole payload, for the cases that need an instance which answers
    with something other than what was asked for.
    """

    def __init__(
        self, ids: dict[str, str] | None = None, *, answer: dict[str, Any] | None = None
    ) -> None:
        self._ids = ids or {}
        self._answer = answer
        self.calls: list[tuple[str, str]] = []

    async def __call__(self, foreign_id: str, context: str) -> dict[str, Any]:
        self.calls.append((foreign_id, context))
        if self._answer is not None:
            return self._answer
        numeric = self._ids.get(foreign_id)
        if numeric is None:
            return {"total": 0, "results": []}
        return {"total": 1, "results": [{"id": numeric, "foreign_id": foreign_id}]}


def resolver(
    lookup: Any = _refuse_to_look_up,
    *,
    timeout_secs: float = 30.0,
    monotonic: Any = None,
) -> CollectionResolver:
    return CollectionResolver(
        lookup=lookup,
        timeout_secs=lambda: timeout_secs,
        **({"monotonic": monotonic} if monotonic is not None else {}),
    )


# -- parse: every refusal that needs no upstream -------------------------------

# Each row is refused by reading the value alone. The message fragment is asserted because
# a scope refusal that does not say which value is wrong sends the caller back to guessing.
SCOPE_REFUSALS: list[tuple[Any, str]] = [
    ("", "must not be empty"),
    ("   ", "must not be empty"),
    ("\n", "must not be empty"),
    ([], "at least one collection"),
    ([""], "must not be empty"),
    ([ALL_COLLECTIONS, "874"], "cannot be combined"),
    (["874", ALL_COLLECTIONS], "cannot be combined"),
    # A repeated literal beside a named collection is still a mixed scope. Without these,
    # counting the literal instead of testing every element passes -- and then `"*"`
    # survives into the resolved scope as a foreign_id, costing a lookup before failing.
    ([ALL_COLLECTIONS, ALL_COLLECTIONS, "874"], "cannot be combined"),
    (["874", ALL_COLLECTIONS, ALL_COLLECTIONS], "cannot be combined"),
    (list(range(MAX_SCOPE_COLLECTIONS + 1)), f"at most {MAX_SCOPE_COLLECTIONS} collections"),
    ("42\n", "expected a numeric collection id"),
    ("874 874", "expected a numeric collection id"),
]


@pytest.mark.parametrize(
    ("collection", "fragment"), SCOPE_REFUSALS, ids=[str(row[0]) for row in SCOPE_REFUSALS]
)
async def test_a_scope_that_names_nothing_is_refused_without_a_lookup(
    collection: Any, fragment: str
) -> None:
    """The evidence for "a refused call costs no collection lookup", at the layer that decides it.

    The lookup passed here fails the test rather than answering, so a refusal that moved
    to after the request would fail with that assertion instead of passing quietly.
    """
    with pytest.raises(ValueError, match=fragment):
        await resolver().resolve_scope(collection, context="search_entities")


ONE_COLLECTION_REFUSALS: list[tuple[Any, str]] = [
    (ALL_COLLECTIONS, "addresses exactly one collection"),
    ("", "must not be empty"),
    ("  ", "must not be empty"),
    ("42\n", "expected a numeric collection id"),
]


@pytest.mark.parametrize(
    ("collection", "fragment"),
    ONE_COLLECTION_REFUSALS,
    ids=[str(row[0]) for row in ONE_COLLECTION_REFUSALS],
)
async def test_a_single_collection_is_refused_without_a_lookup(
    collection: Any, fragment: str
) -> None:
    """`"*"` is refused here rather than looked up as a foreign_id, because the same
    argument on the search tools uses that literal for every collection."""
    with pytest.raises(ValueError, match=fragment):
        await resolver().resolve_one(collection, context="get_collection")


# The method to drive is carried in the row rather than looked up from the value, because
# two `ONE_COLLECTION_REFUSALS` rows are byte-identical to `SCOPE_REFUSALS` rows: a
# membership test routed both to `resolve_scope` and ran them as duplicates. Harmless today
# -- `resolve_scope` delegates to `resolve_one` -- but it is a dispatch that mis-routes
# silently the moment either table changes, which is the shape of bug this file exists to
# catch elsewhere.
_TYPED_REFUSALS = [("resolve_scope", *row) for row in SCOPE_REFUSALS] + [
    ("resolve_one", *row) for row in ONE_COLLECTION_REFUSALS
]


@pytest.mark.parametrize(
    ("method", "collection", "fragment"),
    _TYPED_REFUSALS,
    ids=[f"{row[0]}-{row[1]}" for row in _TYPED_REFUSALS],
)
async def test_every_scope_refusal_carries_the_refusal_type(
    method: str, collection: Any, fragment: str
) -> None:
    """The `pytest.raises(ValueError)` above is now the weaker half of the contract.

    It still holds -- `Refusal` subclasses `ValueError` so a library caller keeps catching
    them -- but it no longer distinguishes a refusal this module chose to make from a
    decoder failure that merely landed on the same base class. The tool seam translates the
    subclass, so a site left bare reaches the model prefixed and is deleted under
    `mask_error_details`.
    """
    context = "search_entities" if method == "resolve_scope" else "get_collection"
    with pytest.raises(Refusal):
        await getattr(resolver(), method)(collection, context=context)


async def test_an_unusable_listing_is_refused_by_type_too() -> None:
    """The two upstream-shape refusals are built by factory functions rather than raised
    inline, which is the spelling most likely to be missed when the type changes."""
    for answer in ({"total": 0, "results": []}, {"status": "error"}):
        with pytest.raises(Refusal):
            await resolver(FakeUpstream(answer=answer)).resolve_one(
                "my-case", context="search_entities"
            )


def test_parse_needs_no_resolver_at_all() -> None:
    """The parse half is a pure function, callable with nothing constructed around it.

    Also pins the input-spelling dedup: `874` and `"874"` are one spelling, so a list
    carrying both costs one resolution rather than two.
    """
    assert parse_scope(ALL_COLLECTIONS) is None
    assert parse_scope([874, "874", "my-case"]) == ("874", "my-case")
    assert parse_scope("my-case") == ("my-case",)
    assert parse_collection(874) == "874"


# -- render: the wire spellings live on the resolved scope ---------------------


def test_a_scope_renders_one_search_filter_per_collection() -> None:
    scope = CollectionScope((ResolvedCollection("874"), ResolvedCollection("12")))
    assert scope.search_filters() == [
        ("filter:collection_id", "874"),
        ("filter:collection_id", "12"),
    ]


def test_a_scope_renders_the_match_endpoint_its_own_spelling() -> None:
    """Two wire spellings for one concept is why the rendering is a method and not a loop
    at the call site: /api/2/match takes `collection_ids`, everything else takes
    `filter:collection_id`."""
    scope = CollectionScope((ResolvedCollection("874"), ResolvedCollection("12")))
    assert scope.match_filters() == [("collection_ids", "874"), ("collection_ids", "12")]


def test_a_single_collection_renders_the_listing_filter() -> None:
    assert ResolvedCollection("874").filters() == [("filter:collection_id", "874")]


def test_every_collection_renders_no_filter_and_reports_the_literal() -> None:
    """Omitting the filter is how Aleph is asked for every readable collection, on both
    endpoints. The reply has to say so, because the request cannot: an empty filter list
    and a deliberate cross-collection search look identical on the wire."""
    scope = CollectionScope(None)
    assert scope.is_every_collection
    assert scope.search_filters() == []
    assert scope.match_filters() == []
    assert scope.reported() == ALL_COLLECTIONS


def test_a_named_scope_reports_the_resolved_ids() -> None:
    scope = CollectionScope((ResolvedCollection("874"), ResolvedCollection("12")))
    assert not scope.is_every_collection
    assert scope.reported() == ["874", "12"]


def test_a_scope_of_no_collections_cannot_be_constructed() -> None:
    """The empty tuple is the one construction that fails open, so the type refuses it.

    It renders byte-identically to the sentinel — no filter, so Aleph answers across every
    readable collection — while reporting `searched.collection: []` and suppressing the
    EVERY COLLECTION note. `parse_scope` cannot produce it; without this guard that is a
    property of the current control flow rather than of the type, and the docstring above
    would be a claim nothing checks.
    """
    with pytest.raises(ValueError, match="names no collection"):
        CollectionScope(())


def test_the_empty_scope_guard_is_a_defect_not_a_refusal() -> None:
    """The one site in this module that must stay a bare `ValueError`.

    It fires only when this repo builds the type wrongly -- `parse_scope` cannot produce an
    empty tuple -- which makes it a defect guard, the same shape as `echo.Policy`'s fail-open
    cap that the refusal retype deliberately left alone. As a `Refusal` it would reach the
    model unprefixed as this server's considered answer, telling it to "pass None for the
    all-collections scope": a parameter no tool exposes and no caller can reach.

    Review found it retyped along with the ten genuine refusals beside it, and mutation then
    showed nothing caught that -- the test above passes for any `ValueError` subclass. This
    is the assertion that was missing.
    """
    with pytest.raises(ValueError) as excinfo:
        CollectionScope(())
    assert not isinstance(excinfo.value, Refusal), (
        "a guard against this repo's own bug must not read as a refusal the caller can act on"
    )


# -- resolve: the lookup, the dedup, the cache, the deadline -------------------


async def test_two_spellings_of_one_collection_collapse_to_one_filter() -> None:
    """A numeric id and a foreign_id naming the same collection are one collection.

    Deduplicating only the input spellings is not enough — they differ as text and agree
    only once resolved. Emitting the filter twice would contradict what the reply reports
    under `searched.collection` and what the one-filter-per-id contract says.
    """
    upstream = FakeUpstream({"my-case": "874"})
    scope = await resolver(upstream).resolve_scope(["874", "my-case"], context="search_entities")
    assert scope.reported() == ["874"]
    assert scope.search_filters() == [("filter:collection_id", "874")]


async def test_the_all_collections_literal_resolves_to_the_sentinel() -> None:
    """`"*"` must arrive as the sentinel, not as a scope of zero collections.

    The two are indistinguishable on the wire and differ only in what the reply says, so
    this is the join between `parse_scope("*") is None` and the rendering tests above —
    which each hold their own end and neither of which pins the path between them.
    """
    scope = await resolver().resolve_scope(ALL_COLLECTIONS, context="search_entities")
    assert scope.collections is None
    assert scope.is_every_collection
    assert scope.reported() == ALL_COLLECTIONS
    assert scope.search_filters() == []


async def test_a_foreign_id_the_instance_does_not_know_is_refused() -> None:
    """An empty listing is a refusal naming the tool that can enumerate collections, not
    an empty scope — an empty scope would search every collection instead."""
    upstream = FakeUpstream({"my-case": "874"})
    resolve = resolver(upstream)
    with pytest.raises(ValueError, match="list_collections"):
        await resolve.resolve_one("no-such-case", context="get_collection")
    assert upstream.calls == [("no-such-case", "get_collection")]
    assert resolve.cached == {}


async def test_a_verified_hit_is_cached_and_costs_one_lookup() -> None:
    """A collection's numeric id never changes, so the cache never needs invalidating."""
    upstream = FakeUpstream({"my-case": "874"})
    resolve = resolver(upstream)
    first = await resolve.resolve_one("my-case", context="get_collection")
    second = await resolve.resolve_one("my-case", context="xref_results")
    assert first == second == ResolvedCollection("874")
    assert upstream.calls == [("my-case", "get_collection")]
    assert resolve.cached == {"my-case": "874"}


async def test_a_resolution_the_upstream_did_not_confirm_is_never_cached() -> None:
    """The listing answers with a collection nobody named — a dropped filter, a loose
    match, a redirect answered by a different listing. That is a refusal, and caching it
    would make one lenient answer permanent for the process lifetime."""
    upstream = FakeUpstream(answer={"total": 1, "results": [{"id": "999", "foreign_id": "other"}]})
    resolve = resolver(upstream)
    with pytest.raises(ValueError, match="list_collections"):
        await resolve.resolve_one("my-case", context="search_entities")
    assert resolve.cached == {}


async def test_the_cache_cannot_be_seeded_from_outside() -> None:
    """Only a verified hit gets in. A writable cache is a way to resolve a collection
    without ever asking the instance whether it is the right one."""
    resolve = resolver(FakeUpstream({"my-case": "874"}))
    await resolve.resolve_one("my-case", context="get_collection")
    with pytest.raises(TypeError):
        resolve.cached["other"] = "999"  # type: ignore[index]
    assert resolve.cached == {"my-case": "874"}


async def test_the_resolution_deadline_stops_a_scope_that_runs_long() -> None:
    """One resolution phase, one deadline, mirroring the shrink loop.

    Each lookup is bounded on its own budget, so N of them in sequence would otherwise
    multiply that budget by N before the search is even sent. The first collection is
    never charged: a scope of one must cost exactly what a single lookup costs.
    """
    upstream = FakeUpstream({"first": "874", "second": "12"})
    ticks = [0.0, 61.0]

    def clock() -> float:
        return ticks.pop(0) if len(ticks) > 1 else ticks[0]

    with pytest.raises(Refusal, match=r"exceeded this call's 30.0s budget after 1 of 2"):
        await resolver(upstream, monotonic=clock).resolve_scope(
            ["first", "second"], context="search_entities"
        )
    assert upstream.calls == [("first", "search_entities")], (
        "the deadline must stop the phase, not merely report it afterwards"
    )


async def test_the_budget_is_read_at_call_time_not_captured() -> None:
    """`AlephClient` passes a callable, not a value, and a comment says why.

    A resolver that captured the budget at construction passes every other test in the
    suite, so that comment was a claim nothing checked — and the claim matters: the
    settings object is what a test adjusts to exercise a short budget, and it is adjusted
    after the client is built.
    """
    upstream = FakeUpstream({"first": "874", "second": "12"})
    budget = [30.0]
    ticks = [0.0, 61.0]

    def clock() -> float:
        return ticks.pop(0) if len(ticks) > 1 else ticks[0]

    resolve = CollectionResolver(lookup=upstream, timeout_secs=lambda: budget[0], monotonic=clock)
    budget[0] = 45.0
    with pytest.raises(Refusal, match=r"exceeded this call's 45.0s budget"):
        await resolve.resolve_scope(["first", "second"], context="search_entities")


async def test_an_upstream_id_echoed_into_a_refusal_is_bounded_and_escaped() -> None:
    """The `id` read out of a listing hit is upstream text on its way to a model.

    Both halves are load-bearing and neither is visible from the other's test: the cap
    comes from `COLLECTION_ECHO`, and the escaping comes from the `!r` at the call site.
    Keeping the policy while dropping the `!r` would silently unstrip the control
    characters that policy deliberately does not strip itself.

    The value now reaches the model through the upstream-malfunction refusal rather than
    through the caller-facing validator — the bound and the escaping are unchanged, and
    this is the test that keeps them covered across that move. The value is quoted at all
    because it is the one branch where the type name is not the diagnosis: `"abc"` and
    `"874"` are both `str`.
    """
    upstream = FakeUpstream(
        answer={"total": 1, "results": [{"id": UPSTREAM_ID, "foreign_id": "my-case"}]}
    )
    with pytest.raises(ValueError) as excinfo:
        await resolver(upstream).resolve_one("my-case", context="search_entities")
    message = str(excinfo.value)
    assert "\x1b" not in message, "a raw control character reached a model-visible message"
    assert "'" + "a" * 60 + "\\x1b" + '"' + "b" * 58 + "… [+2 chars]'" in message
    assert "upstream malfunction" in message, f"an unusable id is not the caller's: {message}"
    assert "the value is neither" not in message, message


# -- the listing's shape is checked before it is indexed -----------------------

# Every shape the resolver can be handed that is not a readable list of records. The
# transport wraps a non-dict JSON body as `{"results": <body>}`, so the string, number and
# bool rows are reachable two ways: Aleph's own dict carrying that value, and a JSON body
# that is not an object at all. An HTML interstitial is deliberately not among them — it
# never reaches this module, because the transport's decode raises on it first.
# The falsy rows are the ones that matter most and are the easiest to leave out: `{}`,
# `""`, `0` and `False` are all non-lists that the old `results or []` read as "empty", so
# a branch order that checks emptiness before type sends every one of them back to the
# missing-collection diagnosis while every truthy row still passes.
UNUSABLE_LISTINGS: list[tuple[str, dict[str, Any]]] = [
    ("no-results-key", {"status": "error"}),
    ("null-results", {"results": None}),
    ("mapping-results", {"results": {"a": 1}}),
    ("empty-mapping-results", {"results": {}}),
    ("number-results", {"results": 5}),
    ("zero-results", {"results": 0}),
    ("bool-results", {"results": True}),
    ("false-results", {"results": False}),
    ("string-results", {"results": "not-a-listing"}),
    ("empty-string-results", {"results": ""}),
    ("null-first-row", {"results": [None]}),
    ("string-first-row", {"results": ["some-other-value"]}),
]


@pytest.mark.parametrize(
    "listing",
    [row[1] for row in UNUSABLE_LISTINGS],
    ids=[row[0] for row in UNUSABLE_LISTINGS],
)
async def test_an_unreadable_listing_is_refused_and_not_called_a_missing_collection(
    listing: dict[str, Any],
) -> None:
    """The shapes this covers used to fail three different wrong ways.

    A truthy non-list `results` reached `results[0]` and raised `KeyError: 0` or
    `TypeError: not subscriptable`, which `server.py` does not translate — so it left this
    server as a FastMCP fault rather than as a refusal. Everything else was reported as
    "no collection with foreign_id X is readable with this API key; call list_collections",
    which is an assertion about the caller's permissions derived from a body that said
    nothing about them. A proxy, an SSO interstitial or an unfamiliar Aleph version
    therefore produced a confident wrong diagnosis and a dead-end next step.
    """
    upstream = FakeUpstream(answer=listing)
    resolve = resolver(upstream)
    with pytest.raises(ValueError) as excinfo:
        await resolve.resolve_one("my-case", context="search_entities")
    message = str(excinfo.value)
    assert "list_collections" not in message, (
        f"an upstream malfunction must not send the caller to list_collections: {message}"
    )
    assert "API key" not in message, (
        f"an upstream malfunction is not an authorisation problem: {message}"
    )
    assert "my-case" in message, f"the refusal must name what was being resolved: {message}"
    assert "upstream malfunction" in message, (
        f"every malfunction branch must carry the same framing: {message}"
    )
    assert resolve.cached == {}, "a listing that could not be read must resolve nothing"


# All three malfunction branches, each with the whole clause it must produce rather than
# just the type name inside it. Asserting the bare token is what let a reworded message
# disarm this test once already: "str" lives inside "upstream" and "int" inside
# "endpoint", so `"str" in message` passed whatever the branch actually said. A clause is
# immune to the surrounding prose changing, which is the only way that regression stays
# closed.
SHAPE_CLAUSES: list[tuple[str, dict[str, Any], str]] = [
    ("no-results-key", {"status": "error"}, "carried no results at all"),
    ("null-results", {"results": None}, "carried no results at all"),
    ("mapping-results", {"results": {"a": 1}}, "carried results as dict, not a list"),
    ("empty-mapping-results", {"results": {}}, "carried results as dict, not a list"),
    ("number-results", {"results": 5}, "carried results as int, not a list"),
    ("zero-results", {"results": 0}, "carried results as int, not a list"),
    ("bool-results", {"results": True}, "carried results as bool, not a list"),
    ("string-results", {"results": "x"}, "carried results as str, not a list"),
    ("null-first-row", {"results": [None]}, "carried a first row as NoneType, not a record"),
    ("int-first-row", {"results": [5]}, "carried a first row as int, not a record"),
    ("string-first-row", {"results": ["x"]}, "carried a first row as str, not a record"),
]


@pytest.mark.parametrize(
    ("listing", "clause"),
    [(row[1], row[2]) for row in SHAPE_CLAUSES],
    ids=[row[0] for row in SHAPE_CLAUSES],
)
async def test_an_unreadable_listing_names_the_shape_it_received(
    listing: dict[str, Any], clause: str
) -> None:
    """The shape is what identifies the malfunction, and it is read rather than assumed.

    A refusal saying only "unusable" tells an operator nothing about which of the three
    things went wrong; `results as dict` says "an object where a list belongs", `a first
    row as NoneType` says "the list is there but its first entry is null". All three
    branches format their own message, so all three are pinned here.

    The whole clause, not the type name inside it. `"str" in message` was satisfied by
    "up**str**eam" and `"int"` by "end**point**", so those assertions passed whatever the
    branch actually emitted — and a reworded message is exactly what turned them vacuous
    the first time.
    """
    upstream = FakeUpstream(answer=listing)
    with pytest.raises(ValueError) as excinfo:
        await resolver(upstream).resolve_one("my-case", context="search_entities")
    message = str(excinfo.value)
    assert clause in message, f"the refusal must say {clause!r}: {message}"


@pytest.mark.parametrize(
    "wrap",
    [lambda body: {"results": body}, lambda body: {"results": [body]}],
    ids=["non-list-results", "non-record-row"],
)
async def test_an_unreadable_listing_never_echoes_the_upstream_body(
    wrap: Any,
) -> None:
    """The type identifies the malfunction; the value is unbounded upstream text.

    Interpolating the body would put an attacker-influenceable string of unknown length
    into the model's context — the defect `bound-ontology-echo` closed on the neighbouring
    path. A type name is a closed vocabulary, so it needs no bound. Asserted on both
    branches: they build their messages separately, so one can grow an echo the other
    does not have.
    """
    # The sentinel sits at offset 0, not after a prefix. With it further in, an echo of
    # the first few characters cleared every assertion here -- no "AAAA", no control
    # character, still under the cap -- while leaking the head of the body.
    body = "SENTINEL" + "\x1b" + "A" * 5000 + "</html>"
    upstream = FakeUpstream(answer=wrap(body))
    with pytest.raises(ValueError) as excinfo:
        await resolver(upstream).resolve_one("my-case", context="search_entities")
    message = str(excinfo.value)
    assert "not a list" in message or "not a record" in message, (
        f"the refusal must still name the shape: {message}"
    )
    assert "SENTINEL" not in message, f"the head of the upstream body was echoed: {message}"
    assert "AAAA" not in message, f"the upstream body must not be echoed: {message[:200]}"
    assert "\x1b" not in message, "a raw control character reached a model-visible message"
    assert len(message) < 500, f"an upstream-shaped refusal must stay bounded: {len(message)}"


async def test_the_empty_listing_is_the_one_shape_that_means_no_such_collection() -> None:
    """Aleph answers a foreign_id nobody owns with a present, empty `results` list.

    That is the only shape this server may read as an authorisation-or-existence problem.
    The companion of the test above: together they pin that the two diagnoses are told
    apart rather than one standing in for both.
    """
    upstream = FakeUpstream(answer={"total": 0, "results": []})
    resolve = resolver(upstream)
    with pytest.raises(ValueError) as excinfo:
        await resolve.resolve_one("no-such-case", context="get_collection")
    message = str(excinfo.value)
    assert "list_collections" in message, f"a genuine miss keeps its next step: {message}"
    assert "no collection with foreign_id" in message, message
    assert resolve.cached == {}


async def test_a_refused_listing_does_not_poison_a_later_good_one() -> None:
    """Fail closed, not fail permanently. Nothing is cached on any refusal path, so the
    same foreign_id resolves normally once the upstream recovers."""
    answers: list[dict[str, Any]] = [
        {"results": 5},
        {"total": 1, "results": [{"id": "874", "foreign_id": "my-case"}]},
    ]

    async def flaky(foreign_id: str, context: str) -> dict[str, Any]:
        return answers.pop(0)

    resolve = resolver(flaky)
    with pytest.raises(ValueError):
        await resolve.resolve_one("my-case", context="search_entities")
    assert resolve.cached == {}
    assert await resolve.resolve_one("my-case", context="search_entities") == ResolvedCollection(
        "874"
    )


# -- the row is a collection record, and it arrived inside a listing -----------

# Every row below is a *record*, so each one clears the four envelope guards and is
# refused for something the row itself says — or fails to say. That is the line this
# change moves: `guard-scope-resolver-shapes` stopped at "the listing is readable" and
# read whatever the first record held as an answer.
UNUSABLE_ROWS: list[tuple[str, dict[str, Any], str]] = [
    ("no-foreign-id-key", {"id": "874"}, "carried a first row with no foreign_id field"),
    ("id-absent", {"foreign_id": "my-case"}, "not a numeric collection id"),
    ("id-null", {"foreign_id": "my-case", "id": None}, "not a numeric collection id"),
    ("id-not-numeric", {"foreign_id": "my-case", "id": "abc"}, "not a numeric collection id"),
    ("id-empty", {"foreign_id": "my-case", "id": ""}, "not a numeric collection id"),
    ("id-mapping", {"foreign_id": "my-case", "id": {"a": 1}}, "not a numeric collection id"),
    ("id-list", {"foreign_id": "my-case", "id": ["874"]}, "not a numeric collection id"),
    ("id-bool", {"foreign_id": "my-case", "id": True}, "not a numeric collection id"),
    # The loose numeric read that `_is_numeric_form` applies to *caller* input has no
    # counterpart here: an upstream id is either a collection id or it is not.
    (
        "id-trailing-newline",
        {"foreign_id": "my-case", "id": "874\n"},
        "not a numeric collection id",
    ),
    ("id-spaced", {"foreign_id": "my-case", "id": "8 74"}, "not a numeric collection id"),
]


@pytest.mark.parametrize(
    ("row", "clause"),
    [(row[1], row[2]) for row in UNUSABLE_ROWS],
    ids=[row[0] for row in UNUSABLE_ROWS],
)
async def test_a_row_that_is_not_a_collection_record_blames_the_upstream(
    row: dict[str, Any], clause: str
) -> None:
    """The diagnosis has to be about the responder, because the call was correct.

    Every one of these used to reach the caller-facing validator or the miss refusal.
    `{"id": "874"}` was reported as "no collection with foreign_id 'my-case' is readable
    with this API key"; the rest as "expected a numeric collection id (got 'None'). A
    foreign_id is accepted directly and resolved for you; this error means the value is
    neither." The caller passed a foreign_id, and the upstream confirmed it one line
    earlier — so "the value is neither" is false about the call, and is asserted absent
    here rather than left to the wording of the replacement.
    """
    upstream = FakeUpstream(answer={"total": 1, "results": [row]})
    resolve = resolver(upstream)
    with pytest.raises(ValueError) as excinfo:
        await resolve.resolve_one("my-case", context="search_entities")
    message = str(excinfo.value)
    assert clause in message, f"the refusal must say {clause!r}: {message}"
    assert "upstream malfunction" in message, f"the diagnosis must name the upstream: {message}"
    assert "list_collections" not in message, (
        f"a malfunction is not a missing collection: {message}"
    )
    assert "API key" not in message, f"nothing here is about authorisation: {message}"
    assert "the value is neither" not in message, (
        f"the caller's value was a foreign_id and it resolved; this sentence is false "
        f"about the call: {message}"
    )
    assert resolve.cached == {}, "an unusable row must cache nothing"


# A row whose `foreign_id` is *present* has made a statement about which collection it is,
# and a statement that does not match is the miss the spec already fixes. `None` is in the
# list because a collection created without a foreign_id serialises exactly that way: it is
# a real record truthfully saying it is not the one asked for.
CONFIRMED_MISSES: list[tuple[str, dict[str, Any]]] = [
    ("different-value", {"id": "874", "foreign_id": "someone-else"}),
    ("null-value", {"id": "874", "foreign_id": None}),
    ("empty-value", {"id": "874", "foreign_id": ""}),
]


@pytest.mark.parametrize(
    "row", [row[1] for row in CONFIRMED_MISSES], ids=[row[0] for row in CONFIRMED_MISSES]
)
async def test_a_row_naming_another_collection_is_still_a_miss(row: dict[str, Any]) -> None:
    """The companion of the test above, and the reason the discriminator is key presence.

    Falsiness would have collapsed `{"foreign_id": None}` into the malfunction branch,
    which would be wrong twice over: it is a shape a well-behaved Aleph produces, and the
    refusal it would get names an upstream fault for a listing that is working.
    """
    upstream = FakeUpstream(answer={"total": 1, "results": [row]})
    resolve = resolver(upstream)
    with pytest.raises(ValueError) as excinfo:
        await resolve.resolve_one("my-case", context="search_entities")
    message = str(excinfo.value)
    assert "no collection with foreign_id" in message, message
    assert "list_collections" in message, f"a genuine miss keeps its next step: {message}"
    assert "upstream malfunction" not in message, message
    assert resolve.cached == {}


# One representative value per key, so a check written against presence passes and one
# written against truthiness fails on `offset`. Aleph's QueryResult emits all five.
ENVELOPE_KEYS: list[tuple[str, Any]] = [
    ("status", "ok"),
    ("total", 1),
    ("page", 1),
    ("limit", 1),
    ("offset", 0),
]


@pytest.mark.parametrize("key,value", ENVELOPE_KEYS, ids=[row[0] for row in ENVELOPE_KEYS])
async def test_any_one_envelope_key_is_enough_to_trust_the_rows(key: str, value: Any) -> None:
    """`offset` is the row that matters: it is `0` on the first page of every listing, so
    a guard written as `if not any(listing.get(k) for k in ...)` refuses a perfectly
    ordinary Aleph reply. Presence, not truth."""
    upstream = FakeUpstream(
        answer={key: value, "results": [{"id": "874", "foreign_id": "my-case"}]}
    )
    resolved = await resolver(upstream).resolve_one("my-case", context="search_entities")
    assert resolved == ResolvedCollection("874")


async def test_rows_with_no_listing_envelope_are_not_trusted() -> None:
    """A bare JSON array of records is what the transport's wrapper produces.

    `Transport.request` turns a non-object body into `{"results": <body>}` and adds
    nothing else, so before this guard a 200 whose whole body was
    `[{"foreign_id": "my-case", "id": "874"}]` resolved to 874 and cached it for the
    process lifetime. Measured. The resolver could not tell an Aleph listing from any
    array that happened to carry the right two keys.
    """
    upstream = FakeUpstream(answer={"results": [{"id": "874", "foreign_id": "my-case"}]})
    resolve = resolver(upstream)
    with pytest.raises(ValueError) as excinfo:
        await resolve.resolve_one("my-case", context="search_entities")
    message = str(excinfo.value)
    assert "no listing envelope" in message, f"the refusal must name the shape: {message}"
    assert "upstream malfunction" in message, message
    assert "list_collections" not in message, message
    assert resolve.cached == {}, "rows outside an envelope must not be cached"


async def test_an_empty_result_set_is_exempt_from_the_envelope_check() -> None:
    """A bare `[]` body keeps reading as a genuine miss, which the spec fixes for it.

    The envelope guard is about trusting *rows*; with none to trust, requiring an envelope
    would reverse a decided question while claiming to be about something else. The test
    exists because the cheapest implementation — check the envelope first — silently does
    exactly that, and every other assertion in this file would still pass.
    """
    upstream = FakeUpstream(answer={"results": []})
    resolve = resolver(upstream)
    with pytest.raises(ValueError) as excinfo:
        await resolve.resolve_one("no-such-case", context="get_collection")
    message = str(excinfo.value)
    assert "list_collections" in message, f"an empty array is still a miss: {message}"
    assert "no collection with foreign_id" in message, message
    assert "no listing envelope" not in message, message


async def test_the_row_guards_run_after_the_shape_guards() -> None:
    """A body that is wrong in two ways gets the more specific of the two diagnoses.

    `["x"]` has no envelope *and* a first row that is not a record. Naming the row shape
    tells an operator which part of the payload to look at; naming the absent envelope
    does not. Pinned because the branch order is the only thing that decides it, and
    reordering the two leaves every other test in this file green.
    """
    upstream = FakeUpstream(answer={"results": ["x"]})
    with pytest.raises(ValueError) as excinfo:
        await resolver(upstream).resolve_one("my-case", context="search_entities")
    message = str(excinfo.value)
    assert "carried a first row as str, not a record" in message, message
    assert "no listing envelope" not in message, message


# -- the all-collections literal means the same in either spelling -------------


@pytest.mark.parametrize(
    "collection",
    [[ALL_COLLECTIONS], [ALL_COLLECTIONS, ALL_COLLECTIONS]],
    ids=["single-element", "repeated"],
)
async def test_a_list_naming_only_the_literal_is_the_all_collections_scope(
    collection: list[str | int],
) -> None:
    """`["*"]` names no other collection, so the mixed-scope refusal described a mistake
    the caller did not make. The scalar `"*"` was always accepted; a caller building the
    argument programmatically produces the list, and paid a turn for the difference.

    The repeated case falls out of asking whether every element is the literal rather than
    whether the list has one element — the same reading as the dedup one branch below.
    """
    assert parse_scope(collection) is None
    scope = await resolver().resolve_scope(collection, context="search_entities")
    assert scope.reported() == ALL_COLLECTIONS
    assert scope.search_filters() == []
