## 1. Launcher credential resolution

- [x] 1.1 Replace both `plugins/aleph/.mcp.json` credential resolver commands with independent Keychain-first, environment-fallback commands; verify their command shape keeps shell evaluation, quiet Keychain errors, raw host scoping, and no refusal marker.

## 2. Executable packaging coverage

- [x] 2.1 Generalize the manifest command helper in `tests/test_packaging.py` and execute each resolver against a temporary fake `security` executable; verify Keychain host/key precedence, host-only key fallback, and full environment fallback without exposing credential values.
- [x] 2.2 Retain the immutable full-SHA install-pin assertion and run `uv run pytest tests/test_packaging.py tests/test_config.py`; verify current launch commands pass while the legacy configuration marker remains rejected.

## 3. Operator documentation

- [x] 3.1 Update `plugins/aleph/README.md` with the two ordered Keychain records, exact storage commands, precedence rule, and legacy migration; verify it describes `aleph-mcp` as the host record and `aleph-mcp:<host>` as the API-key record.
- [x] 3.2 Update `SECURITY.md` to describe explicit environment fallback while retaining non-disclosure and resolved-host scoping guarantees; verify it no longer classifies ambient fallback as an in-scope defect.

## 4. Change validation

- [x] 4.1 Run `openspec validate keychain-environment-credential-fallback --strict`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, and `uv run pytest -q`; verify all local release gates pass.
- [x] 4.2 Sync the `credential-resolution` delta into `openspec/specs/credential-resolution/spec.md`, parse-check that all source-precedence scenarios survive, archive the change, and validate all published specifications.
- [x] 4.3 Reject Keychain stdout from an unsuccessful lookup and make the fake emit diagnostics on a miss; verify the focused manifest tests pass and fail when the success-status guards are removed.
- [x] 4.4 Prove the API resolver ignores failed host-lookup stdout before choosing its host-scoped service; verify the focused test fails when that first status guard is removed.
