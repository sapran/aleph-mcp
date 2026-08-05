## 1. Confirm what is already covered

- [x] 1.1 Re-read `tests/test_readonly.py` and record, per requirement in `specs/read-only-guard/spec.md`, which scenarios already have an assertion. The existing file covers endpoint allow/deny, trailing slash, base-path stripping, a single-hop cross-host redirect and a single-hop redirect into a write.
      - R1 allowlisted pairs only — **covered** for allow/deny and the direct-write case; the allowlist *shape* was not asserted.
      - R2 host and base-path pin — **covered** single-hop; the credential claim was not asserted.
      - R3 every redirect hop — **not covered**. Existing tests are single-hop, and a single-hop test passes even if the guard only ever ran once.
      - R4 encoding — **not covered** at all.
      - R5 query surface — **not covered** at all.
      - R6 `refresh=true` sole exception — **not covered**.
      - R7 transport posture — no test needed; it is a scoping statement, and `tests/test_config.py` already covers host acceptance.
- [x] 1.2 Note any requirement the current code cannot satisfy as written. If one exists, stop and amend the spec — this change must not modify `src/`.
      - None. Every requirement is satisfied by the code as it stands, which is the expected result for a baseline.

## 2. Redirect coverage (mocked)

- [x] 2.1 Add a multi-hop test: an allowlisted request redirecting to another allowlisted request, redirecting to a mutating endpoint. Assert the guard evaluated every hop and the write route was never called. Instrument the hook or count refusals; do not infer hop coverage from the final error alone.
      - `test_guard_runs_on_every_redirect_hop` wraps the installed hook with a spy and asserts the exact three-hop sequence, not just the final error.
- [x] 2.2 Add a 307 test on `POST /api/2/match` redirecting to a mutating endpoint on the same host. Assert the body was not replayed and the write route was never called.
- [x] 2.3 Extend the cross-host redirect test to assert the `Authorization` header was never emitted to the foreign host, not merely that the request was refused.
      - Added as a separate test. **First attempt was vacuous** — it registered the foreign route on the global `respx` router rather than the active one, so the assertion could not fail. Caught by mutation-testing it: with the request hook removed the evil route must receive one call. Rewritten against `respx_mock`, mutation confirmed.
      - Finding worth keeping: httpx strips `Authorization` across a host change on its own, so with the guard removed the leak is `call_count=1, auth=None`. What this server contributes is that the request is never issued. The test docstring says so rather than overclaiming.

## 3. Encoding coverage (mocked)

- [x] 3.1 Add a parametrised test over encoded traversal variants — at minimum `%2F`, `%2e%2e`, `%00`, `;`, and a bare `//` — each shaped to resolve at a mutating endpoint. Assert every one is refused.
      - Six variants, all refused.
- [x] 3.2 Add a test that encoding characters inside an otherwise allowlisted path (`/api/2/entities/e%31`) is allowed and addresses the same endpoint as the decoded form.
- [x] 3.3 Add a test pinning the charset condition the decoded-path match depends on: assert the accepted id character set excludes `%`. This is the tripwire for the requirement's "if ever widened" clause — it must fail if someone adds `%` to `_ENTITY_ID`.
      - `test_id_charset_excludes_percent`, asserting both the pattern text and a rejected sample.

## 4. Query-surface coverage (mocked)

- [x] 4.1 Add a test that drives every tool that accepts a caller-controlled key — `search_entities` (`filters`, `facets`), `expand_entity` (`properties`), `list_entitysets` (`set_type`) — with a value containing `&` and `=`, collects the emitted parameter names, and asserts each is either a known literal or carries a namespaced prefix. Enumerate across tools rather than asserting one call site, so a newly added tool is covered.
      - Shared `_emitted_params` helper drives six calls. Verified non-vacuous: 7 parameter batches collected, including `filter:refresh=true&sync=true` and `facet_size:refresh=true&sync=true` — the hostile value lands *inside* the name, percent-encoded.
- [x] 4.2 Assert no emitted parameter name is a bare caller string, and that the hostile value never produces an additional query parameter.
- [x] 4.3 Add a test asserting `refresh=true` appears on exactly one request across the whole tool surface: `get_collection` by numeric id. This is the tripwire for the named-exception requirement.
      - Drives all eleven client methods and asserts `refreshing == ["/api/2/collections/42"]`.

## 5. Allowlist shape (mocked)

- [x] 5.1 Add a test enumerating the allowlist and asserting every entry is `GET` except a single `POST /api/2/match`. The existing tests check individual paths but never the shape of the whole tuple.

## 6. Close out

- [x] 6.1 Run the mocked suite, ruff and mypy. Do not run `tests/live/`.
      - `pytest`: **139 passed** (124 before; 15 added). `ruff check` / `format`: clean. `mypy`: unchanged pre-existing errors only.
- [x] 6.2 Confirm `git diff -- src/` is empty. This change specifies and tests existing behaviour; any `src/` hunk means it changed behaviour and must be split out.
      - Restated, because nothing is committed yet and the working tree still carries the previous change: **`readonly.py` has 0 hunks**, and the only `src/` hunks are the two in `client.py` belonging to `fix-id-validation-anchors` (`@@ -33,19` validators, `@@ -314,11` `get_collection`). This change touched `tests/test_readonly.py` only, +228/-0.
- [x] 6.3 `openspec validate baseline-read-only-guard --strict`, then sync the delta into `openspec/specs/read-only-guard/spec.md`.
- [x] 6.4 Prune `docs/implementation-notes.md`: both remaining findings — the decoded-vs-raw asymmetry and `refresh=true` — are now requirements with tripwires. Remove them and leave the file empty of stale entries, or delete it if nothing remains.
