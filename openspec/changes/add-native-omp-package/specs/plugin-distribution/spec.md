## Purpose

Define how Aleph MCP is packaged, installed, discovered, verified, upgraded, and removed across omp and Claude Code without crossing harness plugin boundaries.

## ADDED Requirements

### Requirement: Native omp package installs both capabilities

The project SHALL publish a native omp package whose documented install command makes both the Aleph MCP server and `aleph-mcp-entity-graph` skill available to a fresh omp session. Installation SHALL NOT require the `claude-plugins` discovery provider or a hand-written user or project MCP definition.

#### Scenario: Install while Claude marketplace discovery is disabled

- **WHEN** an isolated omp profile has `claude-plugins` in `disabledProviders` and installs the documented native package version
- **THEN** a fresh session discovers the Aleph MCP server with all 17 tools and resolves `skill://aleph-mcp-entity-graph`
- **AND** no MCP server from the Claude Code plugin registry is introduced

#### Scenario: Remove the native package

- **WHEN** the operator runs the documented native plugin uninstall command and starts a fresh session
- **THEN** the Aleph MCP server and `aleph-mcp-entity-graph` skill are absent without requiring manual MCP or skill cleanup

### Requirement: Native package preserves the published Aleph identity

The native omp package SHALL preserve the documented Aleph server and tool identity so installing through the native route does not create a second naming contract.

#### Scenario: Inspect installed server identity

- **WHEN** a fresh session lists MCP servers after native installation
- **THEN** the Aleph server uses the documented plugin namespace and its tools use the documented `mcp__aleph_mcp_<tool>` form

### Requirement: Published package contains only install-time assets

The npm artifact SHALL contain the license, pinned native MCP definition, method skill, and plugin README required for lawful installation and runtime use. It SHALL NOT contain credentials, repository tests, Python source, local configuration, or development-only files. The native and Claude distributions SHALL carry byte-identical method skills, and their MCP server bodies SHALL differ only in the harness-required server key.

#### Scenario: Inspect the packed artifact

- **WHEN** the package is packed from `plugins/aleph-omp/`
- **THEN** its file inventory contains every runtime asset and none of the excluded repository or credential-bearing paths
- **AND** packaging guards prove the duplicated skill and MCP server body have not drifted

### Requirement: Distribution versions remain aligned

The Python package version, Claude marketplace version, Claude plugin version, native omp package version, and version-pinned native install commands SHALL agree for every release. The native package's MCP definition SHALL continue to pin the server source to a full immutable commit SHA.

#### Scenario: Validate release metadata

- **WHEN** the packaging guard runs against a release candidate
- **THEN** all four version declarations and both documented native install versions are identical
- **AND** the MCP source is pinned to a 40-character commit SHA

### Requirement: Harness-specific install instructions are separate

The main README SHALL document the native package route for omp and the marketplace route for Claude Code. It SHALL NOT present the Claude marketplace command as the recommended omp installation path.

#### Scenario: Follow omp installation instructions

- **WHEN** an operator follows only the README's omp install, verify, update, and remove commands
- **THEN** every command addresses the native package and no step requires enabling Claude Code plugin discovery

#### Scenario: Migrate an existing omp marketplace install

- **WHEN** an operator previously installed `aleph@aleph-mcp` through omp marketplace discovery
- **THEN** the omp instructions remove that legacy plugin and marketplace entry from every affected profile and scope before installing the native package
- **AND** removal instructions address both named native profiles and legacy marketplace residue
