## 1. Classify every occurrence of the slug before moving anything

- [x] 1.1 Enumerate every `aleph-entity-graph` occurrence outside `.git` and `openspec/changes/archive`
      and classify each by sense — *this plugin's skill* (must be renamed) versus *the
      `acordia-analysts` consumer* (must stay) — recording the verdict per occurrence; verify by
      showing that the eight live files (`plugins/aleph/README.md`,
      `plugins/aleph/.claude-plugin/plugin.json`, the `SKILL.md` path itself, `tests/test_tools.py`,
      `docs/implementation-notes.md`, `README.md`, `.claude-plugin/marketplace.json`,
      `openspec/specs/mcp-tool-surface/spec.md`) each have a recorded verdict and that no occurrence
      is left unclassified. Follow `skill://multi-sense-token-rename`
- [x] 1.2 Confirm `openspec/changes/archive/**` is excluded from the rename, since an archived change
      records what shipped at the time; verify no archive file appears in the edit set

## 2. Rename this plugin's skill

- [x] 2.1 Move `plugins/aleph/skills/aleph-entity-graph/` to
      `plugins/aleph/skills/aleph-mcp-entity-graph/` with `git mv` and set the frontmatter `name` to
      `aleph-mcp-entity-graph`; verify the new `SKILL.md` exists, the old directory is gone, and
      `git status` shows a rename rather than an add plus delete
- [x] 2.2 Update the sense-1 references from task 1.1 — `plugins/aleph/README.md`,
      `plugins/aleph/.claude-plugin/plugin.json`, root `README.md`,
      `.claude-plugin/marketplace.json` and the `tests/test_tools.py` reference if it names this
      plugin's copy — and verify by grepping the working tree for `skill://aleph-entity-graph` and
      finding only occurrences classified as the `acordia-analysts` consumer
- [x] 2.3 Bump the plugin version in `plugins/aleph/.claude-plugin/plugin.json` and
      `.claude-plugin/marketplace.json` so an installed copy is replaced rather than shadowed;
      verify both files carry the same new version

## 3. Restructure the skill body

- [x] 3.1 Add the call-contract section as the skill's opening content — `entity_id` never `id` or
      `entity`, an identifier comes from a result's `id` and never a `caption`, `schema`/`schemata`
      are top-level and `collection_id` is refused in `filters`, `collection` required on `search_entities` and
      `match_entity`, and that the invocation mechanism is read from the mounted tool schema rather than
      assumed — device-written on hosts that expose devices, a direct call elsewhere; verify by
      reading the file from the start and confirming all five facts appear before any method prose,
      and that both `analyst-skill` call-contract scenarios are satisfied
- [x] 3.2 Add the verbatim dispatch snippet naming `aleph-mcp-entity-graph` and instructing the
      recipient to read it before its first Aleph call; verify the snippet is self-contained by
      checking it needs no other line of the skill to be understood
- [x] 3.3 Add the reporting-discipline section — failed calls appear in the coverage statement, an
      empty result is reported under its stated scope and never as absence, and an upstream service
      failure suspends the conclusion; verify each of the three appears as its own instruction
- [x] 3.4 Rewrite the precision guidance so `filters` and quoted phrases are the stated route to
      precision and the 66%-of-terms widening of a multi-term `q` is named as the reason, keeping
      the facet-first rule that the corpus shows is already followed; verify the section names both
      the `filters` route and the widening behaviour
- [x] 3.5 Strengthen the guardrails to distinguish the two credential classes — the Aleph API
      credential never in a tool argument, shell command, constructed request or log line; credential
      material found in corpus content pivotable only through the server's own tools, with reports
      carrying classification, identifiers and provenance rather than values; verify both scenarios
      in the `analyst-skill` delta are satisfied by the text
- [x] 3.6 Move the profile guidance alone to
      `plugins/aleph/skills/aleph-mcp-entity-graph/references/profiles.md`, leaving the `profile_id`
      trigger in the method text pointing at it, and leaving the entity-set and cross-reference
      guidance in the method text; verify the primary text no longer inlines profile guidance, that
      the trigger names the reference file, and that `list_entitysets`, `get_entityset`,
      `entityset_items` and `xref_results` guidance is still present in the method text
- [x] 3.7 Delete the duplicated seventeen-tool inventory and the hardcoded mount-prefix catalogue,
      while keeping the rule that the prefix and the invocation mechanism belong to the host and the
      instruction to read the mounted tool schema; verify the inventory and prefix catalogue are
      gone and both kept rules are still present
- [x] 3.8 Hold total shipped guidance roughly flat, measured in non-blank lines across the whole
      `plugins/aleph/skills/aleph-mcp-entity-graph/` tree including `references/`: the budget is the
      pre-change `SKILL.md` non-blank line count plus 25%, an allowance sized to the call contract
      and reporting rules net of the inventory and prefix deletions. Verify by recording the
      pre-change count from `git show HEAD:plugins/aleph/skills/aleph-entity-graph/SKILL.md`, the
      post-change tree count, and that the second is within budget — a whole-tree measure so prose
      cannot pass by migrating into the reference file

## 4. Land the spec correction

- [x] 4.1 Apply the `mcp-tool-surface` delta to remove the raw-HTTP-fallback justification from the
      published-names and unprefixed-names requirements and to name both consumers; verify
      `openspec validate` passes for the change and that no scenario text changed
- [x] 4.2 Confirm no server-behaviour change was made: verify the only `src/` file the change
      touches is `src/aleph_mcp/__init__.py`, and only its `__version__` literal. That constant is
      release metadata, not behaviour, and `tests/test_packaging.py` requires it to agree with both
      manifests — so the task 2.3 bump cannot be done without it

## 5. Verify as a consumer

- [x] 5.1 Run the mocked suite and the linters — `uv run pytest tests/`, `uv run ruff check`,
      `uv run ruff format --check`, `uv run mypy src` — and verify all pass; the live suite in
      `tests/live/` is out of scope for this change and is not run here
- [x] 5.2 Read the skill from the built plugin directory as a consumer receives it and verify the
      renamed path is present, no file remains at the old path, and the opening section carries the
      call contract
- [x] 5.3 Verify every `analyst-skill` scenario against the delivered text one by one, recording for
      each the line or section that satisfies it, so an unmet scenario is visible rather than assumed
- [x] 5.4 Verify every figure quoted in `proposal.md`, `design.md` and the spec deltas against the
      committed `evidence/snapshot-2026-09-11_2026-09-18.txt`, which is authoritative. Then re-run
      `evidence/audit_aleph_usage.py` as a sanity check: the window-bounded sections MUST come back
      byte-identical, and any movement in the unbounded diagnostics (`aleph calls found`,
      `session logs scanned`, the spilled-log pass) is expected growth to be recorded and explained,
      never a reason to rewrite the snapshot or the figures derived from it
