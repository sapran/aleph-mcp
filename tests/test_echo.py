"""The bounded-echo rule, one test per policy.

Before this module existed the rule was four helpers with four caps, and no test anywhere
pinned a cap to its number: the closest were `len(value) < 600` and `len(message) < 300`,
both of which survive widening the cap they guard. So a policy's cap and its treatment are
asserted here literally — the expected strings are written out rather than derived from the
policy under test, so a change to the module cannot move the expectation with it.

The four policies differ deliberately; see `aleph_mcp.echo` for why each context needs its
own number. What must not vary is that each one keeps the number it has.
"""

from __future__ import annotations

import pytest

from aleph_mcp import echo
from aleph_mcp.echo import (
    COLLECTION_ECHO,
    PROPERTY_VALUE,
    REQUEST_TARGET,
    SCHEMA_NAME,
    UPSTREAM_ERROR,
    Policy,
    render,
)

# policy, its cap, and the tail it appends when exactly one character is over. The tail is
# part of the contract: a truncated property value says how much it dropped because the
# analyst may want to fetch the rest, where a truncated refusal does not.
CAP_ROWS = [
    (PROPERTY_VALUE, 500, "… [+1 chars]"),
    (COLLECTION_ECHO, 120, "… [+1 chars]"),
    (REQUEST_TARGET, 120, "…"),
    (SCHEMA_NAME, 64, "…"),
    (UPSTREAM_ERROR, 200, "…"),
]


@pytest.mark.parametrize(
    ("policy", "cap", "overflow_tail"),
    CAP_ROWS,
    ids=[policy.name for policy, _, _ in CAP_ROWS],
)
def test_a_policy_caps_at_its_own_length(policy: Policy, cap: int, overflow_tail: str) -> None:
    """Exactly at the cap nothing is added; one character over is cut to the cap and marked.

    Both halves matter. Truncating at the cap but also marking a string that fit would put
    an ellipsis on complete data, and the model cannot tell the two apart.
    """
    assert render("z" * cap, policy) == "z" * cap
    assert render("z" * (cap + 1), policy) == "z" * cap + overflow_tail


def test_every_policy_has_a_cap_row() -> None:
    """A policy added without a row above would ship with its cap pinned by nothing.

    The same tripwire shape `test_every_tool_has_a_forwarding_case` uses on the tool
    surface: enumerate what the module defines, not what the test remembered to list.
    """
    defined = {value.name for value in vars(echo).values() if isinstance(value, Policy)}
    assert defined == {policy.name for policy, _, _ in CAP_ROWS}


@pytest.mark.parametrize(
    "policy", [PROPERTY_VALUE, COLLECTION_ECHO], ids=["property_value", "collection_echo"]
)
def test_a_verbatim_policy_changes_nothing_below_its_cap(policy: Policy) -> None:
    """These two bound length and nothing else, and that is deliberate.

    A property value is returned inside a JSON reply, where the serialiser escapes control
    characters, and the one collection-id echo renders with `!r`, which escapes them too.
    Neither is interpolated raw into a message, so neither strips. Substituting here would
    corrupt data the analyst asked for.
    """
    raw = 'a\n\n  "quoted"\x1b[31m\ttail'
    assert render(raw, policy) == raw


def test_request_target_replaces_unprintable_characters_and_nothing_else() -> None:
    """A refusal names a URL that on a redirect hop the upstream authored, and MCP clients
    render tool errors into terminals — so an ANSI escape or a bidi override in it would be
    interpreted rather than displayed. U+FFFD, not a space, so the damage is visible."""
    assert render("https://a.test/\x1b[2J\npath", REQUEST_TARGET) == ("https://a.test/�[2J�path")
    # Quotes and repeated spaces are left alone: this policy neutralises neither, because
    # its call site does not embed the result between quotes.
    assert render('a  b"c', REQUEST_TARGET) == 'a  b"c'


def test_schema_name_substitutes_visibly_and_leaves_a_real_name_alone() -> None:
    """An FtM schema name is interpolated bare — no `!r`, no surrounding quotes — into a
    refusal and into the ontology listing, so nothing downstream escapes it.

    The substitution doubles as the line flattening: `\\n`, `\\r` and `\\t` are not printable,
    so a multi-line name cannot present as separate lines of server-authored text and no
    separate whitespace collapse is needed. Quotes stay, because there is no quoted region of
    the server's for one to close — neutralising them would only corrupt a legitimate name.
    """
    assert render("Pers\x1b[31mon\x00‮B\ty", SCHEMA_NAME) == "Pers�[31mon��B�y"
    assert render('Person"s', SCHEMA_NAME) == 'Person"s'
    # The longest name in the stock ontology, three and a half times under the cap.
    assert render("ProjectParticipant", SCHEMA_NAME) == "ProjectParticipant"


def test_upstream_error_strips_controls_collapses_lines_and_neutralises_quotes() -> None:
    """All three at once, because all three are needed on this path: the text is embedded
    between double quotes in a message whose label is the only other mitigation, and a
    multi-line body would otherwise present as separate lines of server-authored text."""
    assert render('a\n\n  b\x1b"c"\td', UPSTREAM_ERROR) == "a b 'c' d"


@pytest.mark.parametrize(
    "bad", [["z" * 100_000], b"bytes", {"a": 1}, ("t",)], ids=["list", "bytes", "dict", "tuple"]
)
def test_render_refuses_a_non_string_rather_than_passing_it_through(bad: object) -> None:
    """The verbatim policies skip every transform, so anything with a `__len__` under the
    cap would sail through the length check and come back unshaped. A nested list is what
    `json.loads` yields for an Aleph property value, and the payload is typed `Any`, so the
    `isinstance` guards at the call sites are the only thing enforcing this — and mypy
    cannot check them. Fail loudly at the seam the call sites are told to trust."""
    with pytest.raises(TypeError):
        render(bad, PROPERTY_VALUE)  # type: ignore[arg-type]


@pytest.mark.parametrize("cap", [0, -1, -50])
def test_a_policy_refuses_a_cap_that_would_fail_open(cap: int) -> None:
    """`text[:-1]` slices from the end, so a negative cap emits nearly the whole string and
    still appends the truncation marker — it reads as a bounded echo while bounding nothing.
    A misconfiguration that makes the guard inert must be loud and fatal at construction."""
    with pytest.raises(ValueError, match="max_chars"):
        Policy(name="broken", max_chars=cap)


def test_a_policy_refuses_an_overflow_kind_it_does_not_implement() -> None:
    """`Literal` is erased at runtime, so a typo would fall to the `else` branch and quietly
    downgrade a property value's `… [+N chars]` to a bare ellipsis."""
    with pytest.raises(ValueError, match="overflow"):
        Policy(name="broken", max_chars=10, overflow="Count")  # type: ignore[arg-type]


def test_upstream_error_caps_what_the_model_receives_not_the_raw_body() -> None:
    """Collapsing runs before the cap, so the cap counts characters the model actually gets.

    Capping first would spend the budget on whitespace and then still append an ellipsis,
    reporting a body as truncated when all of its content fits.
    """
    body = ("word" + " " * 10) * 20
    assert len(body) == 280, "the raw body must be over the 200 cap for this to prove anything"
    assert render(body, UPSTREAM_ERROR) == " ".join(["word"] * 20)
