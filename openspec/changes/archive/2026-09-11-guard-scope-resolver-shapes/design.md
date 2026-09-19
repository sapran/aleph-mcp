## Context

Two sites in `src/aleph_mcp/scope.py`, on `develop @ 8c2e480`.

`CollectionResolver.resolve_one` reads a `foreign_id` listing in three lines:

```python
listing = await self._lookup(text, context)
results = listing.get("results") or []
hit = results[0] if results and isinstance(results[0], dict) else None
if hit is None or hit.get("foreign_id") != text:
    raise ValueError(f"no collection with foreign_id {text!r} is readable ...")
```

`listing` is always a dict — `Transport.request` wraps a non-dict JSON body as
`{"results": <body>}` (`transport.py:383`). What is not guaranteed is the `results` *value*. The
`or []` converts a falsy value to an empty list, and `results and ...` short-circuits on a falsy
one; a **truthy non-list** passes both and reaches `results[0]`.

Measured, each an actual run against the live tree:

| lookup body | today |
|---|---|
| `{"results": {"a": 1}}` | `KeyError: 0` |
| `{"results": 5}` | `TypeError: 'int' object is not subscriptable` |
| `{"results": true}` | `TypeError: 'bool' object is not subscriptable` |
| `{"status": "error"}` | "no collection with foreign_id 'acme' is readable with this API key" |
| `{"results": [null]}` | same |
| `{"results": "html page"}` | same — `"h"` is not a dict, so `hit is None` |
| `{"results": []}` | same — and here it is correct |

`server.py:98` catches `ValueError` only, so the first three reach the model wrapped in FastMCP's
"Error calling tool" text. The next three are the confident wrong diagnosis: three different
upstream malfunctions, all reported as an authorisation-or-existence problem with
`list_collections` as the next step.

`parse_scope` handles the literal separately per spelling: the scalar `"*"` returns `None` at
`scope.py:141`; a list containing `"*"` raises the mixed-scope refusal at `scope.py:150`,
whatever else the list holds — including nothing else.

## Goals / Non-Goals

**Goals:**

- No upstream listing shape produces an untranslated exception from the resolver.
- A malfunction and a miss are told apart, and each names the next step that actually helps.
- `["*"]` means what `"*"` means.
- Both refusal paths stay fail-closed and cache nothing.

**Non-Goals:**

- Introducing the `Refusal(ValueError)` type. That is work-plan item 2, which converts every
  refusal site in the client at once; doing it here would couple two changes and force this one
  to pick a channel that item 2 then re-picks. This change raises `ValueError`, the channel
  `scope.py` already uses, and item 2 will migrate it with the rest.
- Guarding any other reader of an upstream body. `scope.py` is the entry this item names; other
  readers are their own entries.
- Retrying or repairing a malfunctioning listing. Fail closed, say why.

## Decisions

**Check the shape in the order the failures happen, not as one predicate.** The three refusals
differ in what they can tell the caller, so they are three branches rather than one
`isinstance(results, list) and results and isinstance(results[0], dict)`. A single predicate can
only produce one message, which is how the current line ended up reporting a malfunction as a
missing collection. The branches are: `results` key absent → malfunction; `results` not a list →
malfunction naming the type; `results` empty → the existing miss; first row not a record →
malfunction. The verified-foreign_id check that follows is unchanged.

**The empty list is the only shape that means "no such collection".** This is the decision the
whole entry turns on. Aleph answers a `foreign_id` nobody owns with `{"results": []}` — present,
a list, empty. Any other unusable shape is a statement about the *responder*, not about the
collection. Reading `{"status": "error"}` as "you cannot see that collection" is not a
conservative default; it is an assertion about the caller's permissions derived from a body that
said nothing about them.

**`None` and a missing key are the same shape.** `{"results": null}` and a body with no `results`
key are both "the listing carried no rows at all" and take one branch. Distinguishing them would
split a message on a difference the caller cannot act on differently.

**Name the type received, not the value.** A malfunction refusal says the `results` value arrived
as `str` / `int` / `dict`, never what it contained. The body is upstream text of unknown length
and provenance; interpolating it would put an unbounded, attacker-influenceable string into the
model's context — the defect `bound-ontology-echo` closed on the neighbouring path. A type name
is a closed vocabulary and is what identifies the malfunction.

**`parse_scope` tests membership after the other-element test, not before.** `["*"]` returns
`None` exactly as the scalar does; the mixed-scope refusal fires only when the list holds `"*"`
*and* something else. Placing the single-element case first also keeps it ahead of the length and
dedup logic below, which have nothing to say about it. The empty list is refused before either,
unchanged.

**`["*", "*"]` resolves to all-collections, not a refusal.** Both elements are the literal, so
the list names no other collection. This falls out of testing "is every element the literal"
rather than "does the list have one element", and is the reading consistent with the deduplication
the function already does for named collections one branch below.

## Risks / Trade-offs

**Two refusal messages change.** A caller matching on the `["*"]` mixed-scope text now gets a
successful all-collections search instead of an error — the behaviour the scalar already had, and
what a caller passing `["*"]` meant. A caller matching on the not-found text still sees it for the
genuine miss; it is the malfunction cases that move to new text, which is the point of the change.
Tests asserting the old texts are updated in the same change.

**A malfunction refusal is less actionable than a miss refusal, on purpose.** "The upstream
answered with an unusable shape" gives the model no argument to change, which is correct: there
is none. The failure mode being removed is the opposite one — an actionable next step that leads
nowhere.

**The shape checks run on every uncached `foreign_id` lookup.** Three `isinstance` calls on a path
that just awaited a network round trip. Not measurable.
