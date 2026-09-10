## Context

`get_model` is the only reader of `/api/2/metadata`. Two consumers sit on it and want
opposite things from a fault:

- `_schemata` → `_reply` → the ten `@_shaped` tools. The model here decides a `caption`, a
  convenience field. Failing ten tools over it is worse than deriving the caption from
  `_CAPTION_FALLBACK`, which is why `_schemata` swallows upstream faults.
- `list_schemata`, `get_schema`, `aleph://schemata`. The model *is* the answer. Serving an
  empty ontology here is not a degradation, it is a false statement about the instance.

That split already exists and is correct. What was missing is a value for "the model is not
usable", so a shape nobody anticipated fell through both paths as an `AttributeError`.

## Goals / Non-Goals

- **Goal:** every non-dict `model` reaches the caller through the same two paths a 503 does.
- **Goal:** a persistently broken metadata route costs a bounded number of upstream requests.
- **Goal:** a caption derived from the fallback order because of a fault is distinguishable
  from one derived from the instance's own ontology.
- **Non-goal:** validating the ontology's *contents*. A `schemata` that is a dict is trusted
  to be one; bounding what it echoes is work-plan item 3, not this change.
- **Non-goal:** making the caption path fail. It degrades, as it does today.

## Decisions

**A truthy non-dict `model` is an upstream refusal, not an empty model.** Caching `{}` for it
would be the third silent degradation in this file, and it would make `list_schemata` state
that the instance has no schemata — which is the wrong answer to "the instance sent
nonsense". The refusal names the JSON type received (`str`, `list`, `int`) and nothing from
the body: the value is upstream text and `errors.py` is where echoing is bounded.

Raised as `ResourceError`, matching `get_model`'s own `resource=True` call and the
`aleph://schema` context it already passes. That is also what makes the degradation
automatic: `_schemata`'s existing `except ResourceError` arm returns `None` for anything
whose cause is not a `ReadOnlyViolation`, so the shaped tools keep answering with no new arm.

**A missing or falsy `model` keeps meaning "no ontology declared".** `payload.get("model") or
{}` treats `{}`, `null` and a missing key alike today, and an instance is entitled to declare
no ontology. Only a *truthy* non-dict is nonsense. Narrowing the change this way keeps every
existing test's meaning intact.

**The negative cache is time-bounded, not permanent.** Permanent negative caching turns one
unlucky 503 into process-long degraded captions, which is a worse failure than the cost it
saves. The window is `_MODEL_FAILURE_TTL = 60` seconds on the same late-bound `_monotonic`
the retry budget, the scope resolver and the shrink loop already share, so one patched clock
governs all four and a test can move it without sleeping.

The cached object is the exception instance itself, re-raised with its traceback cleared. Two
reasons: `_schemata` classifies by type and by `__cause__`, both of which a re-raised instance
preserves, so the degradation stays byte-identical to today's; and clearing the traceback
stops it accumulating a frame per suppressed call across the window.

**The note fires on `None`, not on an empty ontology.** `_schemata` is made to return `None`
only for a fault and `{}` for "read, declares nothing" -- it did not, before this change:
`model.get("schemata")` is `None` for `{"model": {}}` and for a missing `model`, the very
shapes this change defines as a successful read, so keying the note on `None` announced an
unreadable ontology on every reply from a minimal instance. Found in review of this change;
the tail of `_schemata` now collapses every falsy `schemata` to `{}`. A note on `{}` would fire on every
reply from a legitimately minimal instance — and on most of this suite — while saying the
ontology could not be read, which would be false. The note composes with an existing `_note`
rather than replacing it, the way `search_entities`' own notes compose: a truncated page from
an instance whose ontology is down is both, and a caller needs to be told both.

## Risks / Trade-offs

- **A 60-second window is a guess.** It is bounded on both sides by measurement rather than
  taste: at 12 requests per 3 calls, the current cost is unbounded; at one budget per minute
  the cost is bounded and the recovery delay is shorter than a human notices. It is a named
  constant so it can move.
- **A new `_note` is an output change to ten tools.** It appears only when the metadata route
  is failing, which no fixture does by default, and it is additive to a key callers already
  read.
