# Slug occurrence classification (task 1.1)

Every `aleph-entity-graph` occurrence outside `.git` and `openspec/changes/archive`, classified by
sense. Sense 1 = this plugin's own skill, renamed to `aleph-mcp-entity-graph`. Sense 2 = the
`acordia-analysts` consumer, which keeps the original slug.

| File:line | Text refers to | Sense | Verdict |
|---|---|---|---|
| `plugins/aleph/skills/aleph-entity-graph/SKILL.md` (path) | this plugin's skill | 1 | rename directory + frontmatter `name` |
| `plugins/aleph/README.md:11` | "**One skill**, `aleph-entity-graph`" | 1 | rename |
| `plugins/aleph/.claude-plugin/plugin.json:4` | plugin description naming its own skill | 1 | rename |
| `README.md:77` | this repo's shipped skill | 1 | rename |
| `.claude-plugin/marketplace.json:16` | marketplace description of this plugin | 1 | rename |
| `docs/implementation-notes.md:259` | a path into this plugin's skill file | 1 | rename the path |
| `tests/test_tools.py:71` | "the acordia `aleph-entity-graph` skill hardcodes" | 2 | **keep** — names acordia explicitly |
| `openspec/specs/mcp-tool-surface/spec.md:13` | "skill distributed in the `acordia-analysts` plugin" | 2 | keep slug; the delta rewrites this block for other reasons |
| `openspec/config.yaml:4` | "consumed by the `aleph-entity-graph` skill in the acordia-analysts plugin" | 2 | **keep**, untouched |
| `openspec/config.yaml:45` | "the `aleph-entity-graph` skill in the `acordia-analysts` plugin" | 2 | **keep**, untouched |
| `openspec/specs/mcp-tool-surface/spec.md:31` | "the `aleph-entity-graph` consumer" — ambiguous as written | 2 | keep slug; the delta rewrites it to name both consumers explicitly |
| `openspec/specs/mcp-tool-surface/spec.md:55` | "the skill tells its analysts" — the acordia consumer, per the context set at line 13 | 2 | **keep**, untouched by this change |
| `openspec/specs/mcp-tool-surface/spec.md:534` | "skill distributed in the `acordia-analysts` plugin" | 2 | **keep**, untouched by this change |

Unclassified occurrences: none.

## Archive exclusion (task 1.2)

`openspec/changes/archive/**` carries 14 further occurrences across seven archived changes. An
archived change records what shipped at the time, so rewriting it would falsify the record. Every
one is excluded, and no archive file appears in this change's edit set.
