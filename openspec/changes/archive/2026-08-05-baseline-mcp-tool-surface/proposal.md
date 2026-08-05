## Why

This is a **baseline of already-shipped behaviour, not new work.** The MCP surface described here shipped in `695a2ed` ("feat: read-only MCP server over the Aleph HTTP API") and was corrected in `e49567c`; `openspec/specs/` has been empty ever since, so none of it is written down as contract.

That would be tolerable for an internal package. It is not tolerable here, because the surface already has an **external consumer that this repository cannot edit**: the `aleph-entity-graph` skill shipped in the `acordia-analysts` plugin, pinned at `2.0.0`. Its `SKILL.md` names our tools by name and makes two load-bearing promises on our behalf — that the tools "enforce Aleph's real limits" and that they "strip document text out of search hits so it does not silently consume your context". Both promises are currently true by accident of implementation. Nothing tests either one, and the file asserting them lives in a plugin cache outside this repo.

The contract is therefore recorded in three places and specified in none:

- `server.py:11-46` — the `INSTRUCTIONS` string, which restates the method and the ceilings.
- `docs/implementation-notes.md` — two known deviations, written down because there was no spec to put them in.
- `aleph-entity-graph/SKILL.md` — the consumer's copy, versioned separately, unowned by us.

A third place has now been added twice for the same reason. That is the signal.

## What Changes

No behavioural change to the server is proposed. This change writes the existing contract down, and adds the tests that would catch it drifting.

- Add capability `mcp-tool-surface`, covering the twelve registered tools, the three resources, and the response-shape guarantees a caller may rely on.
- Pin the **tool-name contract**: the twelve names are the published interface and renaming one is breaking. Record that `server.py` registers *bare* names (`search_entities`, not `aleph_search_entities`) and that the `aleph_` prefix the consumer skill hardcodes is applied by the mount, not by this server — so the prefix is not ours to guarantee, and the discrepancy is documented rather than silently relied upon.
- Pin the **text-stripping guarantee**: no entity returned by any tool carries a document-sized text property, and anything dropped is named in `_omitted_properties`. This is `_TEXT_BLOB_PROPS` in `client.py:29`, a five-element frozenset; the requirement makes adding a sixth FtM blob property a spec question rather than a silent falsification of the consumer's promise.
- Pin the **refuse-don't-clamp** behaviour: `search_entities` raises on `limit + offset > 9999` where Aleph would silently clamp, and annotates `_note` when the reported total exceeds the reachable window so a large result set reads as *unenumerated* rather than *long*.
- Pin **error translation**: every tool converts `ValueError` to `ToolError`, every resource converts it to `ResourceError`. This is what makes an invalid argument a legible message instead of a transport failure — and it is the rule that `docs/implementation-notes.md` records as already leaky (`entity_id="e1\n"` escapes as an untranslated `httpx.InvalidURL`).
- Add mocked tests for the above. **No live-suite work**: everything asserted here is observable without credentials.

Explicitly **not** in scope:

- The read-only guarantee itself. `readonly.py` deserves its own capability and its own change; per this project's apply guidance the allowlist is never touched as a rider on other work.
- Fixing the two deviations in `docs/implementation-notes.md`. They are recorded as tasks so they stop being an orphan doc, but the fixes are separate changes — a spec that documents current behaviour must not quietly also change it.
- Declaring the cross-root OpenSpec reference to the `acordia` store. Deferred deliberately; see `docs/implementation-notes.md`.

## Capabilities

### New Capabilities

- `mcp-tool-surface`: the tools and resources this server registers, their names as a published contract, the response-shape guarantees callers depend on, and the errors they raise.

### Modified Capabilities

None. `openspec/specs/` is empty; this is the first capability in the repository.

## Impact

- **New files:** `openspec/specs/mcp-tool-surface/spec.md` (on archive); mocked tests covering tool names, text stripping, paging refusal and error translation.
- **Modified code:** none. If writing the spec surfaces a behaviour that cannot be stated honestly, that is a finding to raise, not a licence to edit `src/` inside this change.
- **External consumer:** `aleph-entity-graph` @ `acordia-analysts` 2.0.0 is named in the requirements as the reason the tool-name and text-stripping guarantees are contractual. Nothing in acordia is modified — it is markdown-only by contract and its archived change `2026-07-31-aleph-data-access` already ruled this package out of scope for vendoring.
- **Risk if skipped:** a tool rename here drops that skill to its documented `curl` fallback, which explicitly hands result-bounding back to the model. That failure is silent on both sides.
