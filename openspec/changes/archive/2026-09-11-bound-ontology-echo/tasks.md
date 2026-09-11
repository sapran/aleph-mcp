## 1. Pin the defect before fixing it

- [x] 1.1 Add failing tests in `tests/test_client.py` for `get_schema`'s refusal: a schema name
      carrying `ESC`, `NUL`, `U+202E` and a raw `"` reaches the message intact; a
      20,000-character name produces a ~20,100-character refusal. Watch both go red against the
      current code with the symptom the notes record.
- [x] 1.2 Add failing tests in `tests/test_resources.py` for `aleph://schemata`: a
      20,000-character name is served whole, and the response carries no `_provenance`.

## 2. The policy (mocked suite)

- [x] 2.1 Add `SCHEMA_NAME` to `src/aleph_mcp/echo.py` — cap 64, `unprintable="�"`, no
      whitespace collapse, no quote substitution, `overflow="ellipsis"` — with the rationale for
      each choice beside it, and add its row to the module docstring's table.
- [x] 2.2 Extend `tests/test_echo.py`: `SCHEMA_NAME` in the cap-and-tail parametrisation, in the
      "every policy has a cap row" check, and a test that it substitutes unprintable characters
      visibly while leaving a legitimate name untouched.

## 3. Bound the refusal (mocked suite)

- [x] 3.1 In `src/aleph_mcp/client.py`, render each suggested name under `SCHEMA_NAME` and
      accumulate until the joined list would cross 240 characters, keeping the existing cap of
      10 names and keeping at least one suggestion. Emit no `Did you mean` clause when nothing
      survives.
- [x] 3.2 Turn the 1.1 tests green and add the boundary cases: many names each at the per-name
      cap yield a bounded message with fewer names; an ordinary misspelling still suggests the
      real names character for character.

## 4. Bound and label the listing (mocked suite)

- [x] 4.1 In `list_schemata`, render every name under `SCHEMA_NAME`, cut each of `all`,
      `matchable` and `edges` at 500, keep `count` as the instance's own total, add
      `_omitted_schemata` as a per-list map present only when something was dropped, and add the
      `_provenance` label.
- [x] 4.2 Turn the 1.2 tests green and add: an over-cap ontology reports per-list omissions while
      `count` still names the true total; an ordinary ontology is served whole, labelled, and
      carries no omission key.

## 5. Prove the tests can fail

- [x] 5.1 For each new assertion, reintroduce the defect it guards, confirm it goes red with the
      reported symptom, and restore. Clear `__pycache__` first — a same-size edit survives the
      bytecode cache and certifies nothing.

## 6. Gate

- [x] 6.1 `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy` (the project's own
      gate: `packages = ["aleph_mcp"]`, which is what CI runs), and the full mocked suite green
      with the new tests counted.
- [x] 6.2 Record the out-of-scope finding — `get_schema`'s successful payload echoes unbounded
      upstream `label`/`description` text — in `docs/implementation-notes.md`, and close item 1.

## 7. Live suite (needs a real instance and API key)

- [x] 7.1 Not required for this change: no live test asserts the ontology echo, and the mocked
      suite drives the metadata route directly. Left untouched deliberately.
