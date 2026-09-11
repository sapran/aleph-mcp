## Why

The FollowTheMoney schema names this server reads from `/api/2/metadata` are upstream text —
authored by whoever runs or proxies the Aleph instance — and two paths hand them to the model
unbounded and un-neutralised.

`get_schema`'s "Did you mean one of:" refusal interpolates them bare. Measured against this
branch's parent: a schema key carrying `ESC`, `NUL`, `U+202E` and a raw `"` reaches the message
with all four intact, and a single 20,000-character key produces a 20,100-character refusal. That
message leaves through `aleph://schema/{name}`, whose `_as_resource_error` seam forwards `str(e)`
unprefixed — so it survives `mask_error_details` and arrives in the shape this repo reserves for
caller-actionable refusals. `name!r` sits beside it in the same f-string, is caller input, and *is*
escaped; the upstream half is not.

`aleph://schemata` returns `sorted(schemata)` — every upstream key, unbounded in count and in
length, carrying no `_provenance` label — bounded only by the 25 MiB response ceiling.

`echo.py` already exists as the one home for this rule and already governs the four other
contexts where upstream text reaches the model. The ontology is the context it does not yet cover.

## What Changes

- Add a fifth policy to `echo.py` for an FtM schema name: capped per name, unprintable characters
  substituted visibly, because the name is interpolated without `!r` and nothing downstream
  escapes it.
- Render every suggested name in `get_schema`'s refusal under that policy, and bound the *joined*
  suggestion list by total characters rather than only by count, so ten names cannot together
  restore the unbounded echo the per-name cap removes.
- Render and bound the `aleph://schemata` listing: cap the number of names, render each under the
  same policy, and report what was dropped rather than truncating silently.
- Label `aleph://schemata` with `_provenance`, matching the facet and document-text paths, so the
  model is told the names are upstream-authored rather than this server's vocabulary.
- **BREAKING** for a pathological instance only: a schema name longer than the per-name cap is
  returned truncated by `aleph://schemata` and no longer round-trips into `get_schema`. No real
  FtM name approaches the cap.

## Capabilities

### New Capabilities

None. `echo.py`'s rule is already spec-adjacent behaviour of the tool surface; this extends it to
a context it did not cover.

### Modified Capabilities

- `mcp-tool-surface`: adds a requirement that upstream ontology text reaching the model is bounded
  and neutralised, covering both the `get_schema` refusal and the `aleph://schemata` listing, and
  that the listing declares its provenance and announces its own truncation.

## Impact

- `src/aleph_mcp/echo.py` — one new policy, one new row in the module docstring's table.
- `src/aleph_mcp/client.py` — `get_schema`'s refusal construction, `list_schemata`'s return shape.
- `tests/test_echo.py`, `tests/test_client.py`, `tests/test_resources.py` — the new policy's cap
  and treatment, the two bounded paths, the provenance label.
- No change to `readonly.py`, to the transport, or to the registered tool and resource names.
- The `aleph-entity-graph` skill in the `acordia-analysts` plugin reads `aleph://schemata`; it
  gains a `_provenance` key and, on a pathological instance only, an omission count. Both are
  additive keys on a JSON object it already parses.
