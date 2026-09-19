## Context

`echo.py` is already the one home for the rule that upstream text reaching the model is bounded.
It carries four policies, a table of their caps in the module docstring, and a `render` function
whose transform order is fixed and documented. Each policy's treatment is chosen from a property
of its call site, and the module says so explicitly: two policies keep unprintable characters
*because* their call sites apply `!r`, which escapes them.

The ontology paths were never brought under it. `get_schema` interpolates upstream schema names
bare, beside a `name!r` that is caller input and is escaped; `list_schemata` returns every
upstream key verbatim.

The numbers below are measured against `followthemoney==4.11.0`, read out of the distributed
schema directory: 71 schemata, longest name `ProjectParticipant` at 18 characters, and the worst
three-character prefix cluster — `con` → `Contract, ContractAward, Control` — joining to 32
characters. An Aleph instance may extend the ontology, so the caps carry headroom over those
figures rather than sitting on them.

## Goals / Non-Goals

**Goals:**

- Bring the two ontology echoes under `echo.py`, as a named policy rather than an inline
  transform, so the treatment is stated once and testable in the module that owns the rule.
- Bound the `get_schema` suggestion list by total rendered length, not only by count.
- Bound and label `aleph://schemata`, and make it announce its own truncation.
- Leave the refusal's text unchanged for every ontology that is not pathological, so no existing
  assertion about the message has to move.

**Non-Goals:**

- `get_schema`'s *successful* payload — `label`, `plural`, `description`, and every property's
  `label` and `description` — is also upstream text, unbounded and unlabelled. It is a different
  and wider surface: the caller asked for that record by name, which makes it closer to a property
  value than to a refusal. Recorded in `docs/implementation-notes.md`, not fixed here.
- No change to the matching rule that selects near names (`name[:3]` case-folded prefix). It is
  crude, but changing it would change which suggestions a normal instance produces, which is not
  what this change is about.
- No change to `readonly.py`, the transport, or the registered tool and resource names.

## Decisions

### A fifth policy, `SCHEMA_NAME`: 64 characters, unprintable → `U+FFFD`

Cap 64 is 3.5× the longest name in the stock ontology. It is the per-name bound; a name over it
is cut and marked with an ellipsis.

`U+FFFD` rather than a space, for the reason `REQUEST_TARGET` already gives: this name is
interpolated *without* `!r` and nothing downstream escapes it, so the substitution has to be
visible as damage rather than quietly closing the gap. This also handles newlines without a
separate transform — `str.isprintable()` is false for `\n`, `\r` and `\t`, so a multi-line name
is flattened by the substitution itself, and `collapse_whitespace` would be a no-op after it.

No quote neutralisation, unlike `UPSTREAM_ERROR`. That policy neutralises `"` because its call
site wraps the text in a quoted region a `"` could close early. A schema name is interpolated
bare, in a comma-separated list, with no delimiter of the server's to close. Adding the transform
anyway would corrupt a legitimate name for no gain.

`overflow="ellipsis"` rather than `"count"`, following the rule the `Policy` docstring already
states: a truncated *value* reports what it dropped because the analyst may want to fetch the
rest; a truncated *refusal* reports only that it was truncated, because a character count in a
refusal is noise the model cannot act on.

### The suggestion list is bounded at 240 joined characters, keeping the count cap at 10

The per-name cap alone does not bound the message: ten names at 64 characters is 658 characters
of upstream text, which is the same defect one order of magnitude smaller. So the names are
accumulated until the joined length would cross 240, and the rest are dropped.

240 is 7.5× the worst real prefix cluster (32 characters), so no legitimate suggestion set is
clipped. When it does clip, nothing is lost that the caller cannot recover: the refusal already
ends with `Read aleph://schemata for the full list.`, which is the complete answer the suggestion
list is only a shortcut for. That is what makes an exact number defensible here rather than
load-bearing.

The accumulator keeps at least one suggestion. With a 64-character per-name cap the first name
can never exceed the 240 budget on its own, so this is structural rather than defensive — but it
is what stops the clause from ever degrading to `Did you mean one of: ?`.

### `aleph://schemata`: 500 names per list, per-list omission counts, `_provenance`

Each of the three lists — `all`, `matchable`, `edges` — is rendered name by name under
`SCHEMA_NAME` and cut at 500, roughly 7× the stock ontology's 71. Capping all three matters:
`matchable` and `edges` are subsets of `all`, so bounding only `all` would leave a hostile
instance a shorter but still unbounded path through either subset.

`count` keeps reporting the instance's own total, not the length of the served list. The resource
answers *what this instance declares*; serving a clipped list under a clipped count would state
something false about the instance, and the existing spec requirement that an unusable model must
not be reported as an ontology of zero already establishes that reading.

Truncation is announced under `_omitted_schemata`, a per-list map of counts, present only when
something was actually dropped. A single scalar was the alternative — it is what `_slim_facet`
uses for `_omitted_values` — but that path bounds one list, and here the three lists clip by
different amounts. Absent on every ordinary instance, so it costs a normal reply nothing.

`_provenance` follows the shape the facet slimmer and `get_entity_text` already use:
`trust: "untrusted"` plus an `origin` naming where the text came from. The names are this
server's own vocabulary in the model's eyes otherwise, which is exactly the confusion the label
exists to prevent.

## Risks / Trade-offs

- **A pathological name stops round-tripping.** A name longer than 64 characters is served
  truncated by `aleph://schemata` and will not then resolve through `get_schema`. The alternative
  — serving it whole so it round-trips — is the defect being fixed. No stock FtM name is within
  3× of the cap.
- **Two absurd names can render identically.** Two distinct 20,000-character names sharing a
  64-character prefix both render to the same string and appear as duplicate entries. Honest
  enough — it shows there are two — and it cannot happen to a real ontology.
- **An extended ontology above 500 schemata gets a clipped listing.** It says so, in
  `_omitted_schemata`, and `count` still names the true total. The previous behaviour on such an
  instance was an unbounded response, so this is strictly better, not a new ceiling.
- **An additive key on a resource an out-of-repo consumer parses.** The `aleph-entity-graph`
  skill in `acordia-analysts` reads `aleph://schemata` to pick schema filters. It reads named
  keys off a JSON object, so `_provenance` and `_omitted_schemata` are additions it ignores, and
  no key it reads changes name or meaning.
