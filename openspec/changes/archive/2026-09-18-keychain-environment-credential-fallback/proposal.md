## Why

The shipped Aleph MCP launcher currently gets its host only from the parent environment and replaces an inherited API key with a Keychain result or a refusal marker. Operators need a deliberate, host-scoped credential source that prefers their macOS login Keychain while retaining explicit environment credentials as a portable fallback when the Keychain record is unavailable.

## What Changes

- Add a launcher credential-resolution contract for `plugins/aleph/.mcp.json`.
- Resolve `ALEPHCLIENT_HOST` from the `aleph-mcp` Keychain service before its inherited environment value.
- Resolve `ALEPHCLIENT_API_KEY` from the `aleph-mcp:<resolved-host>` Keychain service before its inherited environment value, independently deriving the same raw host selection.
- Replace the obsolete launcher refusal-marker behaviour with field-by-field environment fallback when the corresponding Keychain lookup fails or is blank.
- Test launcher command precedence with a fake `security` executable, preserving the configuration guard for legacy manifests.
- Update the plugin and security documentation to describe the new operator-controlled source order and migration.

## Capabilities

### New Capabilities
- `credential-resolution`: Defines how the shipped launcher selects Aleph host and API-key values without exposing a key through diagnostics.

### Modified Capabilities
- None.

## Impact

- `plugins/aleph/.mcp.json`: replaces both environment resolver commands.
- `tests/test_packaging.py`: proves Keychain precedence and environment fallback through executable manifest commands.
- `plugins/aleph/README.md` and `SECURITY.md`: document the revised source and migration model.
- `src/aleph_mcp/config.py`: remains unchanged; its legacy `KEYCHAIN_MISS` validation continues to guard old installed manifests.
