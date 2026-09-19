# Evidence for this change

Every count quoted in `proposal.md`, `design.md` and the spec deltas is produced by
`audit_aleph_usage.py` in this directory, with exactly one documented exception — the 121-line
`acordia-analysts` copy, see "What is frozen, and what is not" below. The committed
`snapshot-2026-09-11_2026-09-18.txt` is the authoritative record of those figures; if a document
disagrees with it, the document is stale.

**The window must end on a complete UTC day, and that is not obvious from the local clock.** This
machine runs at UTC+3, so for three hours after local midnight the current UTC day is still
accumulating calls. An earlier window ending `2026-09-19` looked closed and was not: two runs minutes
apart returned 1,894 then 1,898 executed calls, because sessions were still writing into UTC
`2026-09-18`. The window now ends at `2026-09-18T00:00:00Z`, and two consecutive runs are
byte-identical. A committed snapshot is a record; the closed interval over complete days is what
makes the figures reproducible.

The cost of that correctness is scope: Sep 18's activity is excluded, which is why the executed-call
count is 1,356 rather than the ~1,900 a window through "today" would report. That includes the scope-concentration figure for
the dominant collection scope and the line counts of the documents served under `skill://aleph-entity-graph`,
both of which the script computes; the served-document count joins each `read` to its own result by
id, because matching any log line that merely mentions the slug also counts reads of notes and
reports.

## Reproducing

Run on the host holding the session corpus — measured on the corpus host:

```sh
AUDIT_SESSION_ROOT=<agent-sessions-dir> python3 audit_aleph_usage.py
```

The window is fixed in the source so that a re-run is comparable with the run that produced these
numbers; only the corpus root is supplied, because a session-log path names an internal host and an
agent profile. The upper bound matters as much as the lower one — the corpus keeps accumulating
calls, so an open-ended window would silently measure a longer week on every re-run. The corpus
host's `python3` predates `datetime.UTC`, which is why the script uses `datetime.timezone.utc`.

## Scope, stated exactly

| | |
|---|---|
| Root | the agent session-log directory — the the measured profile **only** |
| Window | `[2026-09-11T00:00:00Z, 2026-09-18T00:00:00Z)` — seven **complete** UTC days |
| Population | tool calls whose `path` argument begins `xd://` and resolves to one of the seventeen registered tool names |
| Measured | 2026-09-19, output recorded in `snapshot-2026-09-11_2026-09-18.txt` |

The root matters: the harness keeps a separate corpus per agent profile, and this change is about
one of them. Figures from another profile are a different population and are not pooled here.

## How a call is identified

- A call is `message.content[].type == "toolCall"`, carrying `id` and an `arguments` **object**.
  The sibling `partialArgs` string is ignored — parsing it instead of `arguments` is how a
  transcript fragment gets mistaken for a tool name.
- The outcome is a later `message.role == "toolResult"` joined on `toolCallId`. Its `isError` is a
  **sibling of `details`**, not a member of it; reading `details.isError` yields `None` for every
  call and looks like "not recorded".
- `details.__synthetic` marks a call the user interrupted. It never executed, so it is excluded
  from the executed-call population entirely and reported separately as an attempt. Leaving such a
  row in the tool mix or the error denominator inflates both: there were 3 in this window.
- Time comes from the **event-level** `timestamp` (ISO-8601 Zulu). `message.timestamp` is epoch
  milliseconds. File mtime is not a substitute: it dates the last write to the session, not the
  call, and selecting on it pulls in sessions from outside the window.
- On this host MCP tools are invoked by **writing a JSON object to an `xd://mcp__aleph_mcp_*`
  device**, so the call body is the `content` argument. A body that does not parse as JSON is
  itself one of the failure classes and is counted, not discarded.

## Denominators

Different claims have different denominators, and the script labels each one rather than reusing
the largest:

- **Tool mix and error rate** — all calls in the window.
- **Argument-shape claims** (facets, filters, quoted `q`, scope concentration) — only searches
  whose body decoded as a JSON object. "Parsed" means the decode succeeded, an empty `{}` included;
  a body that failed to decode is a distinct failure class and is counted as such, never silently
  folded into the empty case.
- **Zero-result rate** — only searches that succeeded and retained a result. A failed or
  interrupted call has no result cardinality and must not enter this denominator.
- **Identifier failures** — the union of three error classes, which is smaller than their sum
  because one reply can match more than one pattern.

## Spilled payloads

Large tool results are spilled out of the JSONL into sibling `*.mcp__aleph*.log` files. A claim of
absence read only from the JSONL is therefore not sound: the field may simply live in the spilled
copy. The script counts both, and reports how many spilled logs carry ordinary entity fields
(`schema`, `caption`) as the denominator that makes a zero meaningful. The spilled-log pass is an
all-corpus secondary check, deliberately not window-bounded: a spilled file cannot be mapped back to
its call by name alone, and for a claim of absence a wider sweep is the conservative direction. It
can therefore grow between runs.

## What is frozen, and what is not

All **window-bounded** sections — every count from `attempts in window` through the dispatch tally,
excluding the explicitly labelled all-corpus spilled-log pass — are reproducible: two consecutive
runs are byte-identical, and a run after `ruff format` rewrote the script matched the snapshot
exactly.

Three outputs are deliberately **not** window-bounded and will grow as analysts keep working:
`aleph calls found`, `session logs scanned`, and the spilled-log pass.

Two of those are pure diagnostics. The spilled-log pass is not: the profile requirement in
`specs/analyst-skill/spec.md` cites all **809** logs to justify a claim of absence, deliberately
sweeping wider than the window because for a negative claim the conservative direction is wider. So
read the 809 as **dated secondary evidence, true as of 2026-09-19**, which supports that
requirement; only its future *growth* is non-normative. A later run reporting more logs does not
weaken the requirement — but a later run reporting a populated `profile_id` would, and that is worth
investigating rather than dismissing as drift.

One figure quoted in the planning artifacts is **not** produced by this script: the 121-line
`acordia-analysts` 6.19.1 copy. The command below proves that copy is **present in the plugin cache
now** — it says nothing about any read of it, and no read of a 121-line document falls inside the
window. State it as a cached copy, never as an observed read; the only reads this evidence supports
are the 84x15 and 101x3 the script reports.

```sh
find <plugin-cache-dir> -name SKILL.md -path '*aleph-entity-graph*' \
  -exec sh -c 'echo "$(wc -l <"$1") $1"' _ {} \; | sort -n
```

## Redaction

The script prints **counts only** — never document text, result payloads, tool arguments, or file
contents. `redact()` replaces any run of 32 or more opaque characters with its length, and is the
function to reach for if a future variant ever needs to print a sample.

This matters here specifically: while measuring, an Aleph API key was found in plaintext in one
session log in this corpus. Nothing in this directory reproduces it, and no result payload is
committed. The corpus itself — 809 spilled logs, ~188 MB — stays on the host.
