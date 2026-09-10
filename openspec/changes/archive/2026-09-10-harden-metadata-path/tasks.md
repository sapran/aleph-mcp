## 1. Give the unusable model a refusal

- [x] 1.1 Add `raise_unusable_model(kind, *, context, resource=False)` to
  `src/aleph_mcp/errors.py`: names the JSON type received, states it is an upstream fault the
  caller cannot act on, and says retrying will not help. Quotes nothing from the body.
- [x] 1.2 In `get_model`, replace `payload.get("model") or {}` with a type check: falsy stays
  `{}`, a truthy non-dict raises through 1.1.

## 2. Bound the cost of a failing metadata route

- [x] 2.1 Add `_MODEL_FAILURE_TTL` to `src/aleph_mcp/client.py` with its rationale.
- [x] 2.2 Add `self._model_failure: tuple[float, Exception] | None` and have `get_model`
  record any exception from the fetch or the type check, then re-raise it.
- [x] 2.3 Have `get_model` re-raise the cached exception, traceback cleared, while the window
  holds, issuing no upstream request; after the window, refetch.

## 3. Signal the degraded caption

- [x] 3.1 Add the fallback-caption note constant to `src/aleph_mcp/client.py`.
- [x] 3.2 In `_reply`, attach it when `_schemata()` returned `None`, composing with an
  existing `_note` rather than replacing it.

## 4. Pin all three

- [x] 4.1 Tests: a truthy non-dict `model` is a refusal naming the type, not an
  `AttributeError`, and it is not answered from cache as an empty ontology by `list_schemata`.
- [x] 4.2 Tests: three shaped calls against a failing metadata route cost one retry budget,
  and a refetch happens once the window has passed.
- [x] 4.3 Tests: the note appears when the ontology could not be read, does not appear when
  the ontology was read and is empty, and composes with `search_entities`' own notes.
- [x] 4.4 Mutation-prove each new test against the pre-change behaviour.
- [x] 4.5 Close work-plan item 1 in `docs/implementation-notes.md` and renumber the plan.
