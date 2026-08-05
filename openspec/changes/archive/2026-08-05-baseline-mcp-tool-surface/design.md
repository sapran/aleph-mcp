## Context

The behaviour being specified already exists and is partly already tested — but at the wrong layer and without a contract behind it.

`tests/test_client.py` covers most of the substance directly against `AlephClient`: `_omitted_properties` (line 42), the `searched` scope disclosure (385, 398, 411), the unenumerated-tail `_note`, and the `MAX_EXPAND` ceiling (226). `tests/test_tools.py` already enumerates the tool set (`test_tool_surface_is_exactly_the_read_set`), refuses deep pagination, and asserts that a bad entity id becomes a tool error.

So this change is not "write tests for untested code". It is: decide which of those assertions are *contract* rather than *implementation detail*, say so in a spec, and close the specific gaps where a promise made to an outside consumer has no test at the layer that consumer actually touches.

The constraint that shapes everything below: **this change must not modify `src/`.** A baseline that also fixes behaviour is no longer a baseline, and the two known deviations in `docs/implementation-notes.md` become impossible to distinguish from newly-introduced bugs.

## Goals / Non-Goals

**Goals:**

- One capability spec that a reader outside this repository can use to depend on this server.
- Test coverage at the MCP layer for every requirement whose consumer is external, because a client-layer test does not prove the tool surface honours the same promise.
- Make the `aleph_` prefix discrepancy explicit and settled, rather than a latent surprise.
- Give the orphaned `docs/implementation-notes.md` findings a tracked home.

**Non-Goals:**

- The read-only guarantee. `readonly.py` is a separate capability with a much higher review bar; per this project's apply guidance the allowlist is never touched as a rider.
- Fixing the two known deviations. Recorded as follow-up, not done here.
- Any change to acordia, or the cross-root OpenSpec reference. Both deferred.
- Live-suite work. Nothing in this spec needs credentials to verify.

## Decisions

### Assert the surface at the MCP layer, not the client layer

The requirements are written against tools and resources, so the tests belong in `tests/test_tools.py` and `tests/test_resources.py` via `MCPClient`, even where `tests/test_client.py` already asserts the same property against `AlephClient`.

This looks like duplication and is not. The consumer calls `search_entities` through MCP; what `slim_entity` does in isolation is an implementation fact. If a future refactor registers a tool that bypasses `_slim_result`, the client test still passes and the promise still breaks. The client tests stay as they are — they are finer-grained and catch different regressions.

Alternative considered: keep everything at the client layer and treat `server.py` as a thin pass-through. Rejected — "thin pass-through" is exactly the assumption a regression would violate.

### Document the prefix mismatch rather than resolve it in code

`aleph-entity-graph` hardcodes `aleph_search_entities`. This server registers `search_entities`. Three options:

| Option | Effect |
|---|---|
| Add an `aleph_` prefix here | Breaks every existing mount that already applies its own prefix; hardcodes one host's convention into the server |
| Change the skill | Not ours to change — different repo, pinned at 2.0.0, markdown-only by contract |
| Specify that the prefix is the mount's responsibility | Costs nothing, makes the expectation legible from this side |

Taking the third. The requirement asserts the *absence* of a prefix, so if anyone later adds one to "fix" the skill, the test fails and forces the conversation. This is the honest resolution: the skill's claim is not wrong, it is describing a mounted deployment, and this repo is not the place that mounting happens.

### Requirements name the external consumer in their text

Unusual for a spec, and deliberate. A requirement that says "no tool response carries document-sized text" reads as a nice-to-have that a future contributor may trade away under pressure. The same requirement that says *why* — because a named skill in a named plugin tells its analysts to rely on it — does not. This is also what stops the third shadow copy of the contract from appearing.

### Scope the spec to the surface, not to Aleph's semantics

`get_collection`'s statistics block, `entity_tags`' pivot semantics and `xref_results`' meaning are Aleph's behaviour, not this server's. The spec pins what this server adds or withholds — names, stripping, refusal, scope disclosure, error translation. Everything else is Aleph's contract and specifying it here would create a second source of truth that goes stale when Aleph changes.

## Risks / Trade-offs

- **The enumeration test is a merge-friction feature, not a bug.** Adding a thirteenth tool will fail CI. That is the point — it forces the author to notice the surface is published. Cost is a small edit; benefit is that no tool is ever added or renamed silently.
- **Naming an external consumer in a spec creates a stale-reference risk.** If `acordia-analysts` drops the skill or renames its tools, the rationale text becomes wrong while the requirement stays right. Accepted: the requirements are independently justified and the consumer is cited as evidence, not as the sole reason.
- **Writing the spec may surface behaviour that cannot be stated honestly.** Notably `get_collection`'s `refresh=true`, which asks the server to do work — already recorded in `docs/implementation-notes.md`. This spec avoids the question by not specifying `get_collection` semantics, which is a deliberate deferral rather than an oversight; it belongs with the read-only capability where the "read-only" claim is actually made.
- **`_omitted_properties` is now contractual.** Callers may branch on its presence, so removing it later is breaking. This is intended, and it is the reason the "nothing dropped means no marker" scenario is specified explicitly rather than left to chance.
