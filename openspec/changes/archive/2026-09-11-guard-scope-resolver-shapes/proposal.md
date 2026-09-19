## Why

The collection scope resolver reads an upstream listing with one guard and draws one conclusion
from everything that guard rejects. Three consequences, all measured on `develop @ 8c2e480`:

- A dict body whose own `results` key is not a list reaches `results[0]` and raises `KeyError: 0`
  (`{"results": {"a": 1}}`) or `TypeError: 'int' object is not subscriptable` (`{"results": 5}`,
  `{"results": true}`). The tool seam translates `ValueError` only, so these reach the model as a
  FastMCP server fault rather than as a legible refusal.
- Every other unusable listing — `{"status": "error"}` with no `results` key at all,
  `{"results": [null]}`, a non-dict body wrapped as `{"results": "html page"}` — is reported as
  *"no collection with foreign_id X is readable with this API key; call list_collections"*. A
  proxy, an SSO interstitial or an unfamiliar Aleph version therefore produces a confident wrong
  diagnosis and a dead-end next step: the model is told to fix its authorisation when the upstream
  is malfunctioning.
- `collection=["*"]` is refused with *"cannot be combined with named collections"* — for a list
  that names no other collection. The scalar `"*"` is accepted. The message describes a mistake
  the caller did not make.

The first is the server's own untranslated crash; the second is the most expensive kind of wrong
answer this server can give, because it is confident and actionable; the third costs a turn.

## What Changes

- The resolver SHALL check the listing's shape before indexing it, and refuse an unusable listing
  as an upstream malfunction rather than crashing.
- An unusable listing SHALL be distinguished from a genuine miss. Only an empty `results` list —
  the shape Aleph returns for a foreign_id nobody owns — keeps the existing authorisation-or-
  existence message naming `list_collections`. Every other unusable shape gets a refusal that
  names the malfunction and does not send the caller to `list_collections`.
- **BREAKING** (refusal text only, no signature change): `collection=["*"]` is accepted as the
  all-collections scope, identical to the scalar `"*"`, instead of being refused. A list mixing
  `"*"` with named collections is still refused, unchanged.
- Both refusal paths stay fail-closed: no resolution is returned and nothing is cached when the
  listing cannot be trusted.

## Capabilities

### New Capabilities

None. Every change here sharpens a requirement the `mcp-tool-surface` spec already makes about
collection scope.

### Modified Capabilities

- `mcp-tool-surface`: the *One vocabulary for collection scope across the tool surface*
  requirement gains the listing-shape contract — which upstream shapes are a miss and which are a
  malfunction, and that the two are told apart in the refusal. The *A search must name its
  collection scope* requirement is corrected: a single-element `["*"]` names the all-collections
  scope rather than being a scope that names nothing.

## Impact

- `src/aleph_mcp/scope.py` — `CollectionResolver.resolve_one` (listing shape) and `parse_scope`
  (the `["*"]` branch). No other module changes; no new dependency; no tool signature changes.
- `tests/test_scope.py` — new coverage for each rejected shape and for `["*"]`.
- Two refusal messages change text. A caller that matched on the old `["*"]` message sees a
  success instead; a caller that matched on the not-found message still sees it for the genuine
  miss.
