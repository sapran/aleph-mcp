"""The one home for the rule that upstream text reaching the model is bounded.

Anyone who can get a file ingested into a readable collection, or who sits in front of
the instance as a proxy, authors text that this server may quote back. An unbounded echo
is a write primitive into the model's context; an un-neutralised one can close a quoted
region early and continue as if it were server-authored guidance. So every such string is
rendered here before it leaves the module that obtained it.

The caps differ per context on purpose, and flattening them would be a behaviour change:
a facet bucket label at 500 characters is data the analyst asked for, while an error echo
at 200 is an aid to the operator, and a refusal naming a redirect target needs only enough
of the URL to identify it. What is shared is the *rule* — decide the treatment once, name
it, and let each call site ask for it by name rather than restate it in a comment.

    policy            cap  unprintable  collapse ws  quotes  overflow
    PROPERTY_VALUE    500  kept         no           kept    count
    COLLECTION_ECHO   120  kept         no           kept    count
    REQUEST_TARGET    120  -> U+FFFD    no           kept    ellipsis
    UPSTREAM_ERROR    200  -> space     yes          -> '    ellipsis

Two of these keep unprintable characters because their only call sites render the result
with `!r`, which escapes them; that is a property of the call site, so it is recorded here
rather than assumed. `readonly.py` additionally drops userinfo and the query string before
asking for a rendering — URL knowledge stays with the module that has the URL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal


@dataclass(frozen=True)
class Policy:
    """How one context renders text that may be upstream-controlled.

    `overflow` is the visible difference between a value and a refusal. A truncated
    property value reports what it dropped — the analyst may want to go and fetch the
    rest — where a truncated error message reports only that it was truncated, because a
    character count in a refusal is noise the model has no use for.
    """

    name: str
    max_chars: int
    unprintable: str | None = None
    collapse_whitespace: bool = False
    quote: str | None = None
    overflow: Literal["count", "ellipsis"] = "ellipsis"


# A property value inside a slimmed entity, a facet bucket label, a tag row. This is
# content the caller asked for, so the cap is generous and the overflow says how much is
# missing; `get_entity_text` exists to read a long value deliberately.
PROPERTY_VALUE: Final = Policy(name="property_value", max_chars=500, overflow="count")

# A collection id echoed back in a refusal. Caller input on every path but one — the id
# read out of a foreign_id lookup is upstream text — and the call site applies `!r`.
COLLECTION_ECHO: Final = Policy(name="collection_echo", max_chars=120, overflow="count")

# A request URL named in a read-only refusal. On a redirect hop it is built from the
# upstream's Location header, and MCP clients render tool errors into terminals, so the
# controls go: ANSI escapes and bidi overrides survive `str.split()`, which collapses
# whitespace only. U+FFFD rather than a space so the substitution is visible as damage.
REQUEST_TARGET: Final = Policy(name="request_target", max_chars=120, unprintable="\ufffd")

# Aleph's own error text, or a transport exception's message, quoted as data inside a
# model-visible message. The label is the only other mitigation on this path and a single
# double quote closes the quoted region early, so the delimiter is neutralised too, and
# the whole thing is collapsed to one line: a multi-line body must not present as
# separate lines of server-authored text.
UPSTREAM_ERROR: Final = Policy(
    name="upstream_error",
    max_chars=200,
    unprintable=" ",
    collapse_whitespace=True,
    quote="'",
)


def render(text: str, policy: Policy) -> str:
    """Render `text` under `policy`, safe to embed in a model-visible message.

    The order is fixed and load-bearing: substitution and collapsing run before the cap,
    so the cap counts the characters the model actually receives. Collapsing a multi-line
    body first is what lets a long one fit at all; capping first would spend the budget on
    whitespace and then still emit the ellipsis.
    """
    if policy.unprintable is not None:
        text = "".join(ch if ch.isprintable() else policy.unprintable for ch in text)
    if policy.collapse_whitespace:
        text = " ".join(text.split())
    if policy.quote is not None:
        text = text.replace('"', policy.quote)
    if len(text) <= policy.max_chars:
        return text
    dropped = len(text) - policy.max_chars
    tail = f"… [+{dropped} chars]" if policy.overflow == "count" else "…"
    return text[: policy.max_chars] + tail
