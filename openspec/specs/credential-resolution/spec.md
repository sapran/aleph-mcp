# credential-resolution Specification

## Purpose

Define deterministic, operator-controlled credential source precedence without disclosing
an API key in diagnostics.

## Requirements

### Requirement: Runtime selects one complete credential pair
The runtime SHALL select both `ALEPHCLIENT_HOST` and `ALEPHCLIENT_API_KEY` from exactly
one source, in this order: inherited process environment, `.env` in the current working
directory, then macOS login Keychain. It SHALL not combine a partial pair from one source
with values from another.

#### Scenario: Inherited environment takes precedence
- **WHEN** the parent process supplies both `ALEPHCLIENT_HOST` and `ALEPHCLIENT_API_KEY`
  and the project `.env` and Keychain contain different complete pairs
- **THEN** the runtime uses the inherited pair

#### Scenario: Project dotenv takes precedence over Keychain
- **WHEN** the inherited environment does not contain both credentials, `<cwd>/.env`
  contains both, and Keychain contains a different complete pair
- **THEN** the runtime uses the project dotenv pair

#### Scenario: Keychain is the final fallback
- **WHEN** neither the inherited environment nor `<cwd>/.env` contains a complete pair
- **THEN** the runtime reads `aleph-mcp-host` and `aleph-mcp-api-key` under the login
  account and uses them only when both values are non-empty

#### Scenario: A partial higher-priority source is not combined
- **WHEN** an inherited environment or project `.env` supplies only one credential and a
  lower source supplies a complete pair
- **THEN** the runtime ignores the partial source and uses the complete lower pair

### Requirement: Credential loading is non-executable and non-disclosing
The runtime SHALL parse the project `.env` as configuration data and SHALL NOT
shell-source it. It SHALL not print a Keychain value or lookup diagnostic.

#### Scenario: Legacy launcher marker remains defensively refused
- **WHEN** an older installed launcher explicitly supplies its legacy refusal-marker value
  as `ALEPHCLIENT_API_KEY`
- **THEN** runtime configuration continues to reject that value before it can authenticate
  to an Aleph origin
