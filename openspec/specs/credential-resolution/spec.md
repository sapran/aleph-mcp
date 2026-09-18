# credential-resolution Specification

## Purpose

Define deterministic, operator-controlled credential source precedence for the shipped Aleph MCP launcher without disclosing an API key in diagnostics.

## Requirements

### Requirement: Launcher resolves Aleph host
The shipped Aleph MCP launcher SHALL resolve `ALEPHCLIENT_HOST` from the macOS login-Keychain generic-password item whose service is `aleph-mcp` and whose account is `$USER`. When that lookup exits unsuccessfully or returns an empty value, it SHALL instead preserve the inherited `ALEPHCLIENT_HOST` value.

#### Scenario: Host record takes precedence
- **WHEN** `aleph-mcp` contains a non-empty host while a different inherited `ALEPHCLIENT_HOST` value is present
- **THEN** the launcher supplies the Keychain host

### Requirement: Launcher resolves host-scoped API key
The launcher SHALL independently derive the same raw resolved host while resolving `ALEPHCLIENT_API_KEY`, then resolve that key from the macOS login-Keychain generic-password item whose service is `aleph-mcp:<resolved-host>` and whose account is `$USER`. When that lookup exits unsuccessfully or returns an empty value, it SHALL instead preserve the inherited `ALEPHCLIENT_API_KEY` value. `resolved-host` is selected before runtime host normalization removes a trailing slash or `/api` suffix.

#### Scenario: Both Keychain records take precedence
- **WHEN** `aleph-mcp` contains a non-empty host and `aleph-mcp:<that-host>` contains a non-empty API key while different inherited `ALEPHCLIENT_*` values are present
- **THEN** the launcher supplies the two Keychain values and scopes the key lookup to the host selected from the Keychain

#### Scenario: Host record exists but key record does not
- **WHEN** `aleph-mcp` contains a non-empty host, its corresponding host-scoped key lookup fails or is empty, and an inherited API key is present
- **THEN** the launcher supplies the Keychain host and the inherited API key

#### Scenario: Neither Keychain record is available
- **WHEN** both relevant Keychain lookups fail or return empty values and inherited `ALEPHCLIENT_HOST` and `ALEPHCLIENT_API_KEY` values are present
- **THEN** the launcher supplies those inherited values exactly, without a `KEYCHAIN_MISS` marker

### Requirement: Resolver commands remain independently safe
The resolvers SHALL remain independently correct when the harness evaluates manifest environment entries in any order. They SHALL suppress Keychain lookup diagnostics and SHALL NOT emit a refusal marker in place of either primary credential.

#### Scenario: Manifest environment evaluation order varies
- **WHEN** the harness evaluates the API-key resolver without first evaluating the host resolver
- **THEN** the API-key resolver derives the same raw host selection and scopes its Keychain lookup to that host

### Requirement: Environment fallback remains operator-controlled
When neither relevant Keychain item is available, the launcher SHALL treat the parent process as the deliberate operator-controlled source of its corresponding inherited credential. The launcher SHALL NOT print an API key while resolving credentials, and it SHALL look up a Keychain-sourced API key only through the service scoped to the resolved raw host.

#### Scenario: Legacy launcher marker remains defensively refused
- **WHEN** an older installed launcher explicitly supplies its legacy refusal-marker value as `ALEPHCLIENT_API_KEY`
- **THEN** runtime configuration continues to reject that value before it can authenticate to an Aleph origin
