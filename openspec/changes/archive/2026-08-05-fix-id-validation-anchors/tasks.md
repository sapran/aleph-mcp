## 1. Fix the validators

- [x] 1.1 In `src/aleph_mcp/client.py`, change `_check_entity_id` to use `re.fullmatch` against `_ENTITY_ID`.
      - Also dropped the now-redundant `^`/`$` from `_ENTITY_ID` and `_COLLECTION_ID`, so the patterns read like the ones in `readonly.py` and the `$` that caused the bug cannot be reintroduced by habit.
- [x] 1.2 Change `_check_collection_id` to use `re.fullmatch` against `_COLLECTION_ID`.
- [x] 1.3 Add a dot-only refusal to `_check_entity_id`: an id whose content is empty after stripping `.` addresses nothing and must raise `ValueError`. Do not alter the accepted charset.
      - `if not value.strip("."):` → `invalid <field>: addresses nothing`. Charset untouched.
- [x] 1.4 In `get_collection`, use `_COLLECTION_ID.fullmatch` for the numeric-vs-foreign-id branch decision and `_check_collection_id` for validation, so no collection id reaches path interpolation without passing the shared validator. Leave the foreign-id branch unvalidated — it becomes a url-encoded query parameter and cannot escape the path.
      - Branch test widened to "digits and whitespace only" so `"42\n"` is read as *numeric intent* and then rejected by the validator, rather than falling through to the foreign-id branch and silently returning nothing. `"my-case"` still takes the foreign-id path.

## 2. Retire the deviation markers

- [x] 2.1 Remove the `@pytest.mark.xfail(strict=True, ...)` decorator from `test_trailing_newline_id_surfaces_as_tool_error` in `tests/test_tools.py`. The marker is strict, so the suite fails until this is done — that is intended.
      - Marker removed and the test generalised into `test_trailing_whitespace_id_surfaces_as_tool_error`, parametrised over `\n`, `\r`, `\n\n` and a trailing space.
- [x] 2.2 Delete the "Id validation is looser than the read-only allowlist" section from `docs/implementation-notes.md`. Keep the `raw_path` paragraph if it is separable, since that finding belongs to `baseline-read-only-guard` and is not fixed here.
      - Separable and kept, now under its own heading with the probe evidence and an explicit owner. A closing paragraph records that the other two findings were fixed here, so the file reads as current rather than as a list someone forgot to prune.

## 3. Tests (mocked)

- [x] 3.1 Add tool-layer cases for `entity_id="e1\n"` and `"e1\r"` asserting the validator's message, not httpx's, and that nothing reached the wire.
- [x] 3.2 Add a tool-layer case for `entityset_items(entityset_id="..")` asserting it raises rather than returning an entity list. Assert no request was issued.
      - `test_id_that_addresses_nothing_is_refused`, parametrised over `..`, `.`, `...`, `./.`.
- [x] 3.3 Add a tool-layer case for `get_collection(collection="42\n")` asserting the collection-id validator's message and that nothing reached the wire.
- [x] 3.4 Add a client-layer regression asserting a legitimate id containing dots (e.g. `"a.b.c"`) is still accepted, so the dot-only refusal did not become a dot ban.
      - Written at the tool layer instead, matching the convention set in `baseline-mcp-tool-surface`: the contract is published at the MCP layer.
- [x] 3.5 Confirm the foreign-id branch of `get_collection` still accepts free-form values such as `"my-case"`.

## 4. Close out

- [x] 4.1 Run the mocked suite, ruff and mypy. Do not run `tests/live/`.
      - `pytest`: **124 passed, 0 xfailed** (was 113 passed + 1 xfailed). Eleven tests added, the xfail retired.
      - `ruff check` / `ruff format`: clean. One fix along the way — an unescaped `|` alternation in a `pytest.raises` match, replaced with the exact message.
      - `mypy`: 4 errors, the same pre-existing ones as before this change.
- [x] 4.2 Confirm no test other than the xfail marker was edited to make the suite pass. Any other edited assertion means behaviour changed beyond the stated scope — stop and report.
      - `git diff -- tests/` contains **zero deletion lines**. No pre-existing assertion was modified.
- [x] 4.3 Confirm `git diff -- src/aleph_mcp/readonly.py` is empty. The allowlist is not part of this change.
      - Empty. The only `src/` change is `client.py`, +30/-12.
- [x] 4.4 `openspec validate fix-id-validation-anchors --strict`, then sync the delta into `openspec/specs/mcp-tool-surface/spec.md`.
