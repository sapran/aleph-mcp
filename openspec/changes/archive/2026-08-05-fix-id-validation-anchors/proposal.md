## Why

`baseline-mcp-tool-surface` recorded a requirement the code does not satisfy, and left a strict-xfail test and a spec note behind to mark it. This change removes both by fixing the defect.

The id validators in `src/aleph_mcp/client.py` anchor with `re.match` plus `$`. In Python, `$` matches before a trailing newline, so `entity_id="e1\n"` passes validation. The id then reaches `httpx`, which refuses to build the URL and raises `InvalidURL`. Because each `@mcp.tool` wrapper catches only `ValueError`, the caller receives an error carrying httpx's message — `Invalid non-printable ASCII character in URL, '\n' at position 18` — instead of a statement of the accepted id form. `"e1\r"` is rejected correctly, which is what makes the behaviour confusing rather than merely wrong.

This is not a read-only defect. Nothing is sent to Aleph; the request cannot be constructed. It is an error-translation defect, and it violates the requirement *Invalid arguments surface as tool and resource errors* in `openspec/specs/mcp-tool-surface/spec.md`.

Two further findings recorded in `docs/implementation-notes.md` belong with it, because they share a cause — validation that is looser or differently anchored than the guard it is meant to front:

- The id charset permits `.`, so `entityset_id=".."` is accepted and `httpx` normalises the dot segment away, turning `/api/2/entitysets/../entities` into `/api/2/entities` — an allowlisted read. Confirmed to fail closed, so this is a legibility bug, not an escalation: a nonsense id should be refused, not silently answer a different question.
- `get_collection` is the one method with no `_check_*` call. It branches on `_COLLECTION_ID.match`, which carries the same `$` flaw, and interpolates straight into the path. Its non-numeric branch is safe — that value becomes a `filter:foreign_id` query parameter, url-encoded and unable to escape the path.

## What Changes

- Anchor the id validators with `re.fullmatch` (or `\Z`) so a trailing newline is a `ValueError` like every other invalid character.
- Route `get_collection`'s numeric branch through `_check_collection_id` rather than matching inline, so no entity- or collection-id path interpolation bypasses validation.
- Reject ids that are composed only of dot segments, so `".."` fails with a clear `ValueError` instead of quietly resolving to a different endpoint.
- Remove the `xfail(strict=True)` marker from `test_trailing_newline_id_surfaces_as_tool_error`. The marker is strict, so leaving it in place turns the fix into a suite failure — that is the intended forcing function.
- Remove the **Known deviation at baseline** paragraph from the `mcp-tool-surface` requirement it qualifies.
- Update `docs/implementation-notes.md`: delete the id-validation section, which becomes historical once fixed.

**Not in scope:** `readonly.py`. The allowlist is untouched — this change makes validation agree with the guard, it does not alter the guard.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `mcp-tool-surface`: the requirement *Invalid arguments surface as tool and resource errors* loses its known-deviation carve-out and gains scenarios pinning trailing-newline and dot-segment ids as validation errors.

## Impact

- **Modified code:** `src/aleph_mcp/client.py` — `_check_entity_id`, `_check_collection_id`, `get_collection`.
- **Modified tests:** `tests/test_tools.py` (drop the xfail marker), plus client-layer cases for the newline, dot-segment and `get_collection` paths.
- **Modified docs:** `docs/implementation-notes.md`, `openspec/specs/mcp-tool-surface/spec.md`.
- **Behaviour change for callers:** inputs that previously produced an httpx message now produce a validation message. No input that previously succeeded begins failing — every affected id already failed, just illegibly.
- **Verification:** mocked suite only. Nothing here needs a live Aleph.
