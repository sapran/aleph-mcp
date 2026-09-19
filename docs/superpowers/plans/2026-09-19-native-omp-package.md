# Native omp Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish Aleph MCP as a native omp package that installs the MCP server and method skill without enabling Claude marketplace discovery.

**Architecture:** `plugins/aleph/` remains the Claude marketplace bundle, whose loader prefixes key `mcp` with `aleph:`. A new `plugins/aleph-omp/` npm package carries an explicit `aleph:mcp` key for omp's native loader. Packaging tests enforce exact artifact inventory, equal MCP server bodies, byte-identical skill trees, and four-way version alignment.

**Tech Stack:** npm package metadata, omp native plugins, Python 3.12, pytest, uv, OpenSpec.

**Spec:** `openspec/changes/add-native-omp-package/design.md` and `openspec/changes/add-native-omp-package/specs/plugin-distribution/spec.md`

## Global Constraints

- Keep `claude-plugins` disabled throughout the native omp acceptance journey.
- Do not create user or project MCP definitions, skill symlinks, install scripts, or postinstall hooks.
- Preserve the documented `aleph:mcp` and `mcp__aleph_mcp_<tool>` identity; stop and revise the design if native discovery changes it.
- The npm artifact contains runtime plugin assets only and no credentials.
- Do not change the Aleph tool surface, credential resolver, or read-only allowlist.

---

### Task 1: Native package contract

**Files:**
- Create: `plugins/aleph-omp/package.json`
- Create: `plugins/aleph-omp/.mcp.json`
- Create: `plugins/aleph-omp/README.md`
- Create: `plugins/aleph-omp/skills/aleph-mcp-entity-graph/SKILL.md`
- Create: `plugins/aleph-omp/skills/aleph-mcp-entity-graph/references/profiles.md`
- Modify: `tests/test_packaging.py`

**Interfaces:**
- Consumes: `aleph_mcp.__version__` and the Claude bundle under `plugins/aleph/`.
- Produces: public npm package `@sapran/aleph-mcp-plugin` with server key `aleph:mcp` and an exact runtime inventory.

- [ ] **Step 1: Write failing bundle, manifest, and inventory tests**

Set `NATIVE_ROOT = ROOT / "plugins" / "aleph-omp"` and `NATIVE_PACKAGE = NATIVE_ROOT / "package.json"`. Assert the package metadata, absence of lifecycle scripts, exact `npm pack --dry-run --json --ignore-scripts` inventory, native server key, equal MCP server bodies, and recursive equality of both skill trees:

```python
EXPECTED_NATIVE_FILES = {
    ".mcp.json",
    "LICENSE",
    "README.md",
    "package.json",
    "skills/aleph-mcp-entity-graph/SKILL.md",
    "skills/aleph-mcp-entity-graph/references/profiles.md",
}

assert set(native_manifest["mcpServers"]) == {"aleph:mcp"}
assert native_manifest["mcpServers"]["aleph:mcp"] == claude_manifest["mcpServers"]["mcp"]
```

Compare each skill tree as `{relative_path: bytes}` maps so added, removed, renamed, and modified files all fail.

- [ ] **Step 2: Verify RED**

Run: `uv run pytest tests/test_packaging.py -q`

Expected: FAIL because `plugins/aleph-omp/` does not exist.

- [ ] **Step 3: Add the minimal native bundle**

Create `package.json` with name `@sapran/aleph-mcp-plugin`, version `0.5.1`, repository directory `plugins/aleph-omp`, an empty `omp` manifest, public publishing, no scripts, and `files` limited to `.mcp.json`, `LICENSE`, `README.md`, and `skills`. Copy the repository `LICENSE` into the package root.

Copy the Claude bundle's skill tree byte-for-byte. Create `.mcp.json` with the same server body as `plugins/aleph/.mcp.json` under key `aleph:mcp`. Write an omp-only README that documents the native install lifecycle.

- [ ] **Step 4: Verify GREEN and artifact contents**

Run: `uv run pytest tests/test_packaging.py -q`

Run: `npm pack --dry-run --json --ignore-scripts` from `plugins/aleph-omp/`.

Expected: tests pass and inventory equals `EXPECTED_NATIVE_FILES`.

- [ ] **Step 5: Commit**

```bash
git add plugins/aleph-omp tests/test_packaging.py
git commit -m "feat: package Aleph as a native omp plugin"
```

### Task 2: Native discovery acceptance journey

**Files:**
- Test: disposable omp profile and native package link.

**Interfaces:**
- Consumes: native package root from Task 1.
- Produces: evidence that the native loader supplies the server and skill with Claude marketplace discovery disabled.

- [ ] **Step 1: Establish the RED control**

Create a uniquely named disposable profile with `claude-plugins` in `disabledProviders`, no Aleph package, and no Aleph MCP config. In a fresh process, show that `/mcp list` omits Aleph and `omp --profile <name> read skill://aleph-mcp-entity-graph` fails.

- [ ] **Step 2: Link only the native package**

Run `omp --profile <name> plugin link <absolute-worktree>/plugins/aleph-omp`. Do not edit `mcp.json`, native skill roots, or `disabledProviders`.

- [ ] **Step 3: Verify GREEN**

From a fresh process, assert:

```text
aleph:mcp connected
17 tools
skill://aleph-mcp-entity-graph resolves
mcp__aleph_mcp_list_collections is present
context7 is absent
```

If the actual namespace differs, stop. Do not change documentation to bless a second identity.

- [ ] **Step 4: Verify uninstall**

Run `omp --profile <name> plugin uninstall @sapran/aleph-mcp-plugin`, start a fresh process, and prove both capabilities are absent. Confirm the disposable profile's exact path before removing it.

- [ ] **Step 5: Record the real TUI evidence**

Use a managed interactive `omp --profile <name>` process and run `/mcp list`. Print mode is prohibited because `/mcp list` is routed to the model there and can be fabricated.

### Task 3: Harness-specific documentation

**Files:**
- Modify: `README.md`
- Modify: `plugins/aleph/README.md`
- Modify: `plugins/aleph-omp/README.md`

**Interfaces:**
- Consumes: verified package name, version, server identity, and uninstall behavior from Tasks 1-2.
- Produces: separate, executable omp and Claude Code install contracts.

- [ ] **Step 1: Rewrite install lifecycle instructions**

Update the main README's omp install, verify, update, and remove commands to use `@sapran/aleph-mcp-plugin@0.5.1`. Keep marketplace commands only in the Claude Code path. Make `plugins/aleph/README.md` Claude-specific and `plugins/aleph-omp/README.md` omp-specific.

- [ ] **Step 2: Verify command ownership**

Search the three README files and confirm every `omp plugin` command names the native npm package, while every `aleph@aleph-mcp` command is confined to Claude Code instructions or historical explanation. Confirm no omp instruction tells users to enable `claude-plugins`.

- [ ] **Step 3: Verify prose**

Run the Write skill's English punctuation gate on all three changed README files.

- [ ] **Step 4: Commit**

```bash
git add README.md plugins/aleph/README.md plugins/aleph-omp/README.md
git commit -m "docs: use the native omp package install path"
```


### Task 4: Release and registry-backed proof

**Files:**
- Modify: `src/aleph_mcp/__init__.py`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `plugins/aleph/.claude-plugin/plugin.json`
- Modify: `plugins/aleph-omp/package.json`
- Modify: `README.md`
- Modify: `plugins/aleph-omp/README.md`
- Modify: both plugin `.mcp.json` files after tagging, following the repository's two-commit release order.

**Interfaces:**
- Consumes: reviewed and merged package change.
- Produces: tagged repository release plus published `@sapran/aleph-mcp-plugin` artifact.

- [ ] **Step 1: Run repository gates**

Run:

```bash
uv run pytest tests/test_packaging.py -q
uv run pytest -q
uv run ruff check .
uv run mypy
openspec validate --all --strict
```

- [ ] **Step 2: Review and merge**

Run correctness and silent-failure reviews, resolve every finding, create the PR, wait for CI, and merge only after review is clean.

- [ ] **Step 3: Cut the repository release**

Bump the four metadata version literals and both documented native install versions. Run
the focused packaging test, commit the release, merge `develop` to `main`, and tag that
merge commit. Push the tag and create the GitHub release.

Repoint both `.mcp.json` files at the tagged commit in the required follow-up commit.
Before publishing, rerun the focused packaging test and this pack inspection:

```bash
npm pack --dry-run --json --ignore-scripts
```

Confirm the package contains the expected version, immutable pin, license, README, MCP
definition, and complete skill tree.

- [ ] **Step 4: Publish the npm package**

From `plugins/aleph-omp/`, run `npm publish --access public` only after confirming
authenticated publisher access and that the exact version is not already present.

- [ ] **Step 5: Verify the registry artifact**

Install the exact published version into a clean disposable omp profile with `claude-plugins` disabled. Repeat the full Task 2 GREEN and uninstall journey. The release is incomplete if registry-backed behavior differs from the linked-package probe.
