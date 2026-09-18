## Context

The existing `.mcp.json` host resolver simply forwards the inherited host. Its API-key resolver reads `aleph-mcp:$ALEPHCLIENT_HOST` from the macOS Keychain and emits a fixed `aleph-mcp:keychain-miss` value on a miss. The manifest environment entries are harness-evaluated shell commands, so their order cannot be assumed. See `proposal.md` for motivation.

## Goals / Non-Goals

**Goals:**
- Make the launcher independently select each primary credential from the Keychain first, then from its inherited environment value on a missing or blank lookup.
- Scope a Keychain API-key lookup to the raw host selected under the same precedence rule.
- Prove the shell commands through a fake Keychain executable without exposing credentials in test diagnostics.
- Preserve runtime rejection of the legacy marker as compatibility protection for old installed manifests.

**Non-Goals:**
- Change `Settings` into a Keychain client or change its environment-only boundary.
- Add a credential store for non-macOS systems.
- Normalize the host before deriving the Keychain service name.
- Preserve the prior fail-closed behaviour when the operator intentionally supplies both credentials through the parent environment.

## Decisions

### Source resolution stays in the manifest
The launcher already owns source resolution. Each manifest command will call `security find-generic-password` with stderr discarded, print a non-empty result, and otherwise print its own inherited environment fallback. Keeping this in the manifest avoids platform-specific subprocess logic in application configuration.

### The API-key command derives its own host
The API-key command first performs the host lookup into local shell variable `h`, falls back to its inherited host only when the Keychain value is absent, and looks up `aleph-mcp:$h`. It does not rely on a prior `ALEPHCLIENT_HOST` manifest evaluation, which preserves correctness for arbitrary harness ordering.

### Tests exercise the installed-command shape
Packaging tests will obtain either resolver command from the manifest, assert the leading `!` convention, and run it with an isolated `PATH` where a temporary fake `security` executable chooses responses by requested service. This establishes source precedence and host-scoping without a real login Keychain or printed test secret.

### Documentation treats the old `aleph-mcp` record as a migration
The old service name becomes the preferred host record. Documentation directs operators to overwrite it with the host URL using `-U`, then store the API key only under `aleph-mcp:<host>`.

## Risks / Trade-offs

- An un-migrated installation with an API key still stored under `aleph-mcp` treats that key as a host and fails runtime host validation rather than using it as a credential. The upgrade documentation makes this migration explicit.
- Environment fallback trusts the parent process by design. It provides portable startup where the Keychain command is unavailable, but does not retain the old protection against an untrusted inherited environment.
- A Keychain host containing a trailing slash or `/api` produces a correspondingly raw host-scoped service name. This is intentional: source selection occurs before `Settings._normalise_host`.
