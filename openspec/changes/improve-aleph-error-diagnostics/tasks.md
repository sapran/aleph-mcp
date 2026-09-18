## 1. Retry facts on a retryable refusal

- [x] 1.1 Extract the `Retry-After` read out of `_retry_delay` in
  `src/aleph_mcp/transport.py:137` into one parser returning a tagged result with
  three states — `absent`, `invalid`, `seconds(float)` — with `seconds` bounded by
  `MAX_RETRY_SLEEP_SECS`. Verify the type has a distinct representation for each state
  (no `None`-overloading). Verify
  `_retry_delay` behaviour is unchanged for absent, valid, over-ceiling and unparseable
  headers, and that the header is read in exactly one place: `grep -rn "Retry-After" src/`.
- [x] 1.2 Add the two inputs to `raise_for_status` in `src/aleph_mcp/errors.py` — whether
  the status is retryable, and the parser's result for the final response. Default them so
  every existing caller keeps its current behaviour; verify by reading each call site and
  confirming none needs editing to compile.
- [x] 1.3 Compose the clause: retryability, attempt count, and one of three mutually
  exclusive wait statements — the ceiling-normalised advertised value, unusable, or *the
  final response advertised no next wait*. The message must not describe the value as the
  wait this call would have taken. Verify each of the three for a `503` with `attempts=4`, and that
  the raw header text never appears in the message.
- [x] 1.4 Call the parser on the terminal response at the `give_up` branch
  (`transport.py:251` currently skips it) and pass both values to `raise_for_status`. Verify
  `_RETRY_STATUS` still has exactly one reader: `grep -rn "_RETRY_STATUS" src/`.
- [x] 1.5 Verify the reported value is the advertised value normalised by the ceiling
  alone: for an over-ceiling header assert the message states the ceiling, not the header
  value; and with a remaining budget narrower than the advertised wait, assert the reported
  value is unchanged and the message does not claim the call would have waited it.
- [x] 1.6 Confirm a non-retryable status gains nothing: verify a `404` and a `403` message
  are byte-identical to their current text.
- [x] 1.7 Confirm the existing `budget_spent` clause still appears, and reads coherently
  beside the new one rather than repeating the attempt count.

## 2. Identifier source clause

- [x] 2.1 Add a per-field source clause to `_check_entity_id` in
  `src/aleph_mcp/client.py:105`, keyed on `field`, covering `entity_id`, `profile_id` and
  `entityset_id`. Verify each of the three refusals names its own source and no other's.
- [x] 2.2 Verify the clause is unconditional: refuse two values for one field, one
  resembling a rendered label and one not, and confirm both messages carry the same clause.
- [x] 2.3 Verify the charset, the echo of the rejected value, and the addresses-nothing
  refusal at line 112 are unchanged.

## 3. Tests

- [ ] 3.1 Mutation-prove each new assertion: reintroduce the old message, confirm the test
  fails with the reported symptom, restore. Record which mutation produced which failure.
- [x] 3.2 Re-read every existing test asserting on these two messages. Error wording is the
  published contract here, so update each to the new contract and add exact assertions for
  the retry facts and the per-field source clauses; delete one only where the delta makes
  what it asserts obsolete, recording which and why.
- [x] 3.3 Verify no test asserts a wait value where the fixture's final response carried no
  `Retry-After` — that would encode the invented-wait behaviour this change refuses.
- [x] 3.4 Cover the earlier-attempt case: a fixture whose first response advertises a wait
  and whose final one does not, asserting the message limits its claim to the final
  response.

## 4. Land the spec

- [ ] 4.1 Apply the `mcp-tool-surface` delta: one added requirement, one modified. Verify
  `openspec validate --strict` passes and that the modified requirement's untouched
  paragraphs are byte-identical to the published ones.
- [ ] 4.2 Verify every scenario in the delta against the delivered behaviour one by one,
  recording for each the assertion or output that satisfies it, so an unmet scenario is
  visible rather than assumed.

## 5. Verify

- [ ] 5.1 Run the mocked suite and the linters: `uv run pytest tests/`,
  `uv run ruff check`, `uv run ruff format --check`, `uv run mypy src`. The live suite in
  `tests/live/` needs credentials and is not run here.
- [ ] 5.2 Exercise the two messages through the tool seam rather than by calling the
  validator directly, so the text a caller actually receives is what was checked.
- [ ] 5.3 Confirm the diff touches only `src/aleph_mcp/errors.py`,
  `src/aleph_mcp/transport.py`, `src/aleph_mcp/client.py`, `tests/`, and
  `openspec/`: `git diff --stat`.
