## Context

The guard was probed adversarially before this spec was written, and it held: three-hop redirect chains, 307 body replay, cross-host key leakage, and six traversal/encoding variants were all refused. So this is not a hardening exercise. It is the act of writing down a guarantee that currently exists only as code, plus deciding what to do about the one place where the guarantee as *stated* is broader than the guarantee as *enforced*.

The proposal named that gap: the allowlist matches `(method, path)`, and query strings are not checked. It left three options open for this design to settle.

## Goals / Non-Goals

**Goals:**

- State the refusal behaviour as a contract, expressed as what is refused.
- Settle the query-string question with evidence rather than by picking the most cautious-sounding option.
- Capture the two conditions that would silently invalidate today's safety: the `%` charset condition on decoded-path matching, and the growth of the `refresh=true` exception.
- Record the transport posture as a position, not an omission.

**Non-Goals:**

- Changing `readonly.py`. This change is expected to add tests and a spec and to leave the allowlist byte-identical.
- Re-testing the live path. `e534a6b` already asserts the guard against a live instance; the guard refuses client-side, so mocked tests exercise the real code path.
- The `raw_path` migration. It is specified as a *condition*, not scheduled as work — the charset does not include `%` today.

## Decisions

### The query-string gap is closed at the client, not at the guard

This is the substantive decision, and the proposal's three options were all wrong because they assumed the gap was open. It is not.

Every query parameter this server emits is either a literal it chose (`limit`, `offset`, `q`, `facet`, `highlight`, `refresh`, `collection_ids`, `sort`) or a caller value confined behind a namespace (`filter:{key}`, `facet_size:{facet}`, `facet_total:{facet}`). Probed directly: passing `refresh=true&sync=true` as a filter key, a facet name, an expand property, a search term, and a collection foreign id produced, in every case, either a namespaced parameter with the `&` and `=` percent-encoded inside the *name*, or an ordinary parameter *value*. No call produced a bare second parameter.

So the correct specification is not a deny list and not a per-endpoint parameter allowlist. It is a requirement naming the invariant that actually holds — no caller value may introduce a bare parameter name — with a test that would fail the moment someone adds a parameter built from an unprefixed caller string.

Rejected alternatives:

| Option | Why not |
|---|---|
| Deny list of side-effecting parameters | A blocklist is always incomplete, and it would imply the guard checks queries when it does not. |
| Per-entry allowlist of permitted parameters | Enumerating parameters for twelve endpoints, re-derived on every Aleph release. High rot, and it fails closed on legitimate reads. |
| Leave it undocumented | The state this change exists to end. |

The requirement also says plainly that the allowlist matches method and path only. A reader who does not know that will assume the opposite, and that assumption is exactly how a genuine query-borne side effect would get through review.

### `refresh=true` is specified as a named exception, not removed

Dropping it means `get_collection` returns stale statistics — and those statistics are the denominator the whole documented working method depends on ("read it before searching, to know what the data actually contains"). The cost of removal is real; the cost of keeping it is a sentence.

So it is kept and named, with the requirement written so the exception cannot grow quietly: any second request of this kind requires amending the requirement. That converts an audit finding into a tripwire.

### Two invalidating conditions are requirements, not notes

Both live in `docs/implementation-notes.md` today, which is where findings go to be forgotten:

- The decoded-path match is safe **because** the id charset excludes `%`. That is a dependency between two files that nothing enforces.
- `refresh=true` is acceptable **because** it is the only one.

Each is written into the requirement that depends on it, so a reader of the spec sees the condition alongside the guarantee rather than in a document they may never open.

### The guarantee is scoped away from transport confidentiality

`http://` hosts and `verify_tls: false` are permitted. Neither weakens refusal — an attacker who can read or forge the connection still cannot make this server issue a write. Rather than silently permitting them, the spec states the boundary: "this server cannot write" is not "this connection is trustworthy". Someone who needs the second guarantee now knows to configure for it.

## Risks / Trade-offs

- **A spec that adds no tests would be theatre.** The four properties verified by hand during review — redirect-hop coverage, 307 body replay, cross-host key non-emission, encoded traversal — are none of them in the suite. If this change ships only a document, the guarantee is exactly as unprotected as before. The tests are the deliverable; the spec is the reason they exist.
- **Namespace-prefix reasoning is a construction argument, not a guard.** It holds because of how `search_entities` and `expand_entity` build parameters today. A new tool that appends an unprefixed caller-derived name would break it without touching `readonly.py`. The test enumerates emitted parameter names across tools rather than asserting on one call site, so a new tool is covered by construction.
- **Specifying `refresh=true` legitimises it.** Accepted deliberately. The alternative — leaving it undocumented so it looks like an oversight rather than a decision — is worse for exactly the external audit the proposal is worried about.
