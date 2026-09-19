#!/usr/bin/env python3
"""Reproduce every count quoted in this change's proposal, design and specs.

Run on the host holding the agent session corpus:

    AUDIT_SESSION_ROOT=<sessions-dir> python3 audit_aleph_usage.py

It prints counts only. It never prints document text, result payloads, tool
arguments, or any token that could be a credential: see `redact()` and the
`--no-values` contract in evidence/README.md.

Scope, fixed deliberately so a re-run is comparable:
  root   $AUDIT_SESSION_ROOT                          (one agent profile ONLY)
  window event timestamps >= 2026-09-11T00:00:00Z   (UTC, inclusive)
"""

from __future__ import annotations

import collections
import datetime as dt
import glob
import json
import os
import re
import sys

# The corpus root is supplied by the operator, never hardcoded: a session-log path
# names an internal host and an agent profile, and this file is public.
ROOT = os.environ.get("AUDIT_SESSION_ROOT", "")
# The snapshot window is CLOSED at both ends: [CUTOFF, END). An open upper bound
# is not a comparable scope, because the corpus keeps accumulating calls and a later
# re-run would silently measure a longer week.
CUTOFF = dt.datetime(2026, 9, 11, tzinfo=dt.timezone.utc)  # noqa: UP017 - must run on older pythons
END = dt.datetime(2026, 9, 18, tzinfo=dt.timezone.utc)  # noqa: UP017 - exclusive

# Bare tool names the server registers. Longer names first so `get_entity_text`
# is not swallowed by `get_entity`.
TOOLS = [
    "list_collections",
    "get_collection",
    "search_entities",
    "get_entity_text",
    "get_entity",
    "expand_entity",
    "entity_tags",
    "similar_entities",
    "match_entity",
    "get_profile",
    "profile_tags",
    "profile_similar",
    "expand_profile",
    "list_entitysets",
    "get_entityset",
    "entityset_items",
    "xref_results",
]

SECRETISH = re.compile(r"[A-Za-z0-9_\-]{32,}")


def redact(text: str) -> str:
    """Replace any long opaque token with its length, never its value."""
    return SECRETISH.sub(lambda m: f"<redacted len={len(m.group(0))}>", text)


_LABELS: dict[str, str] = {}


def label(session: str) -> str:
    """A stable, non-identifying label for a session log.

    Session and subagent names are investigation metadata — they carry operation
    and target names. This file is public, so the output never prints them; a
    label is assigned in first-seen order instead.
    """
    if session not in _LABELS:
        _LABELS[session] = f"session-{len(_LABELS) + 1:02d}"
    return _LABELS[session]


def in_window(stamp) -> bool:
    """True when an event-level ISO timestamp falls in [CUTOFF, END)."""
    if not isinstance(stamp, str):
        return False
    try:
        when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    return CUTOFF <= when < END


def tool_of(device: str) -> str | None:
    """Map an `xd://mcp__<mount>_<tool>` device path to a bare tool name."""
    for name in TOOLS:
        if device.endswith(name) or f"_{name}" in device:
            return name
    return None


def parse_session(path: str):
    """Yield one record per Aleph call in one session log.

    Schema notes that cost a re-run if got wrong:
      * a call is `message.content[].type == "toolCall"`, carrying `id` and a
        real `arguments` OBJECT (not the serialized `partialArgs` string);
      * the outcome is a later `message.role == "toolResult"` joined on
        `toolCallId`, whose `isError` is a SIBLING of `details`, not inside it;
      * `details.__synthetic` marks a call the user interrupted - it never ran,
        so it is neither a success nor an error;
      * the authoritative time is the event-level `timestamp` (ISO-8601 Zulu).
        `message.timestamp` is epoch milliseconds. File mtime is NOT a
        substitute: it dates the last write to the session, not the call.
    """
    calls: dict[str, dict] = {}
    order: list[str] = []
    for line in open(path, errors="replace"):
        try:
            event = json.loads(line)
        except ValueError:
            continue  # sibling *.log files are not JSON; skip quietly
        stamp = event.get("timestamp")
        when = None
        if isinstance(stamp, str):
            try:
                when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError:
                when = None
        message = event.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "toolCall":
                    cid = part.get("id")
                    if not isinstance(cid, str):
                        continue  # no id means no result can be joined to it
                    args = part.get("arguments")
                    calls[cid] = {
                        "name": part.get("name") or "",
                        "args": args if isinstance(args, dict) else {},
                        "when": when,
                        "error": None,
                        "synthetic": False,
                        "result": "",
                    }
                    order.append(cid)
        if message.get("role") == "toolResult":
            cid = message.get("toolCallId")
            if cid in calls:
                details = message.get("details") or {}
                calls[cid]["synthetic"] = bool(details.get("__synthetic"))
                calls[cid]["error"] = bool(message.get("isError"))
                body = message.get("content")
                if isinstance(body, list):
                    calls[cid]["result"] = " ".join(
                        p.get("text", "") for p in body if isinstance(p, dict)
                    )
                elif isinstance(body, str):
                    calls[cid]["result"] = body

    for cid in order:
        call = calls[cid]
        path_arg = call["args"].get("path")
        if not (isinstance(path_arg, str) and path_arg.startswith("xd://")):
            continue
        tool = tool_of(path_arg[len("xd://") :])
        if tool is None:
            continue
        # MCP tools are invoked by WRITING a JSON object to an `xd://` device on
        # this host, so the call body is the `content` argument, not the args.
        raw = call["args"].get("content")
        if isinstance(raw, str):
            try:
                body = json.loads(raw)
                parsed = isinstance(body, dict)
            except ValueError:
                body, parsed = {}, False  # non-JSON body: itself a failure class
        elif isinstance(raw, dict):
            body, parsed = raw, True  # already an object, including a valid {}
        else:
            body, parsed = {}, False
        yield {
            "session": os.path.relpath(path, ROOT),
            "tool": tool,
            "when": call["when"],
            "error": call["error"],
            "synthetic": call["synthetic"],
            "body": body if isinstance(body, dict) else {},
            "result": call["result"],
            # parsed == JSON object decoded successfully, empty object included.
            "parsed_body": parsed,
        }


def main() -> int:
    if not ROOT or not os.path.isdir(ROOT):
        print("set AUDIT_SESSION_ROOT to the agent session-log directory", file=sys.stderr)
        return 2

    files = sorted(glob.glob(os.path.join(ROOT, "**", "*.jsonl"), recursive=True))
    rows = [r for f in files for r in parse_session(f)]
    dated = [r for r in rows if r["when"]]
    attempts = [r for r in dated if CUTOFF <= r["when"] < END]
    # `window` is EXECUTED calls only. A `__synthetic` row was interrupted before
    # it ran, so it is neither a success nor an error and must not sit in any
    # rate denominator; it is reported separately as an attempt.
    window = [r for r in attempts if not r["synthetic"]]
    skipped = [r for r in attempts if r["synthetic"]]

    print(f"window                          : [{CUTOFF.date()}, {END.date()}) UTC")
    print(f"session logs scanned            : {len(files)}")
    print(f"aleph calls found               : {len(rows)} ({len(dated)} timestamped)")
    print(f"attempts in window              : {len(attempts)}")
    print(f"  interrupted, never executed   : {len(skipped)}")
    print(f"executed calls in window        : {len(window)}")
    print(f"sessions in window              : {len({r['session'] for r in window})}")
    errors = [r for r in window if r["error"]]
    print(
        f"errors in window                : {len(errors)} "
        f"({100 * len(errors) / max(1, len(window)):.1f}%)"
    )

    print("\n-- tool mix (window) --")
    per_tool = collections.Counter(r["tool"] for r in window)
    per_err = collections.Counter(r["tool"] for r in window if r["error"])
    for tool in TOOLS:
        if per_tool[tool]:
            print(
                f"  {per_tool[tool]:5d}  err={per_err[tool]:3d} "
                f"({100 * per_err[tool] / per_tool[tool]:5.1f}%)  {tool}"
            )
    print("  never called:", ", ".join(t for t in TOOLS if not per_tool[t]) or "-")
    pivots = sum(
        per_tool[t]
        for t in (
            "expand_entity",
            "entity_tags",
            "match_entity",
            "similar_entities",
            "xref_results",
        )
    )
    reads = per_tool["search_entities"] + per_tool["get_entity_text"]
    print(
        f"  search+text {reads} ({100 * reads / max(1, len(window)):.1f}%)  "
        f"graph pivots {pivots} ({100 * pivots / max(1, len(window)):.1f}%)"
    )

    # Denominator discipline: argument-shape claims are only about the calls
    # whose JSON body parsed. Ratios below say so rather than borrowing the
    # tool-mix denominator.
    searches = [r for r in window if r["tool"] == "search_entities" and r["parsed_body"]]
    facets = [r for r in searches if r["body"].get("facets")]
    print(f"\n-- query shape (denominator: {len(searches)} searches with a parsed body) --")
    print(f"  carrying facets               : {len(facets)}")
    print(
        f"  limit=0 survey                : {sum(1 for r in searches if r['body'].get('limit') == 0)}"
    )
    print(
        f"  carrying filters              : {sum(1 for r in searches if r['body'].get('filters'))}"
    )
    print(
        f"  unquoted multi-term q         : "
        f"{sum(1 for r in searches if isinstance(r['body'].get('q'), str) and len(r['body']['q'].split()) >= 3 and chr(34) not in r['body']['q'])}"
    )
    print(
        f"  sessions that ever faceted    : {len({r['session'] for r in facets})} "
        f"of {len({r['session'] for r in searches})}"
    )
    scopes = collections.Counter()
    for r in searches:
        scope = r["body"].get("collection")
        key = ",".join(str(s) for s in scope) if isinstance(scope, list) else str(scope)
        scopes[key] += 1
    # Collection ids name an investigation's datasets, so report the shape of the
    # concentration and not the ids themselves.
    top = scopes.most_common(3)
    print(
        "  scope concentration (top 3)   : "
        + "; ".join(f"scope-{i + 1} x{v}" for i, (_, v) in enumerate(top))
    )

    # Zero-result rate excludes failed calls: a call that errored has no result
    # cardinality and must not enter this denominator.
    answered = [
        r
        for r in window
        if r["tool"] == "search_entities" and not r["error"] and not r["synthetic"] and r["result"]
    ]
    zero = [r for r in answered if re.search(r'"total"\s*:\s*0(?!\d)|\btotal: ?0\b', r["result"])]
    print(f"\n-- absence (denominator: {len(answered)} searches with a retained result) --")
    print(f"  returned zero rows            : {len(zero)}")

    print("\n-- identifier-handling failures --")
    id_calls = [
        r for r in window if r["tool"] in ("get_entity", "get_entity_text", "expand_entity")
    ]
    classes = {
        "wrong argument name": r"is required",
        "caption passed as id": r"invalid entity_id",
        "not found (404)": r"not found \(404\)",
    }
    total_id = 0
    for class_name, pattern in classes.items():
        hits = [r for r in id_calls if r["error"] and re.search(pattern, r["result"])]
        total_id += len(hits)
        print(f"  {len(hits):5d}  {class_name}")
    union = [
        r for r in id_calls if r["error"] and re.search("|".join(classes.values()), r["result"])
    ]
    print(
        f"  {len(union):5d}  union across the three classes, in "
        f"{len({r['session'] for r in union})} sessions"
    )

    print("\n-- infrastructure failures (not caller-preventable) --")
    infra = [
        r
        for r in window
        if r["error"]
        and re.search(r"50[0-9]|not connected|timeout|All connection attempts", r["result"])
    ]
    print(f"  {len(infra):5d}  in {len({r['session'] for r in infra})} sessions")
    worst = collections.Counter(r["session"] for r in infra).most_common(3)
    for session, count in worst:
        print(
            f"         {count:3d} of {sum(1 for r in window if r['session'] == session):3d} "
            f"calls  {label(session)}"
        )

    print("\n-- profile subsystem reachability --")
    populated = sum(1 for r in window if re.search(r'"profile_id"\s*:\s*"[^"]+', r["result"]))
    explicit_null = sum(
        1 for r in window if re.search(r'"profile_id"\s*:\s*(null|"")', r["result"])
    )
    print(f"  replies with a populated profile_id : {populated}")
    print(f"  replies with an explicit null       : {explicit_null}")
    spilled = [
        f
        for f in glob.glob(os.path.join(ROOT, "**", "*"), recursive=True)
        if os.path.isfile(f) and re.search(r"\.mcp__aleph.*\.log$", f)
    ]
    spill_hits = spill_null = carrying_entity_fields = 0
    for f in spilled:
        text = open(f, errors="replace").read()
        spill_hits += len(re.findall(r'"profile_id"\s*:\s*"[^"]+', text))
        spill_null += len(re.findall(r'"profile_id"\s*:\s*(?:null|"")', text))
        if '"schema"' in text and '"caption"' in text:
            carrying_entity_fields += 1
    print(f"  spilled result logs (ALL corpus, not window-bounded): {len(spilled)}")
    print(f"    of those carrying entity fields   : {carrying_entity_fields}")
    print(f"    with a populated profile_id       : {spill_hits}")
    print(f"    with an explicit null             : {spill_null}")

    print("\n-- skill propagation --")
    # A skill invocation is a `read` whose path is `skill://<name>` OR a resolved
    # `.../skills/<name>/SKILL.md`. Counting only the URL form undercounts.

    read_aleph_skill: set[str] = set()
    for f in files:
        session = os.path.relpath(f, ROOT)
        for line in open(f, errors="replace"):
            if "aleph" not in line.lower() or '"read"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not in_window(event.get("timestamp")):
                continue
            message = event.get("message") or {}
            if not isinstance(message.get("content"), list):
                continue
            for part in message["content"]:
                if not (
                    isinstance(part, dict)
                    and part.get("type") == "toolCall"
                    and part.get("name") == "read"
                ):
                    continue
                p = (part.get("arguments") or {}).get("path")
                if not isinstance(p, str):
                    continue
                name = None
                if p.startswith("skill://"):
                    name = p[len("skill://") :].split("/")[0].split(":")[0]
                else:
                    m = re.search(r"/skills/([a-z0-9][a-z0-9-]*)/SKILL\.md", p)
                    name = m.group(1) if m else None
                if name and "aleph" in name:
                    read_aleph_skill.add(session)

    # Which document a read of THIS slug actually returned, identified by the
    # `totalLines` the read reported. This is the collision evidence, so the read
    # must be joined call -> result by id: matching any line that merely mentions
    # the slug also counts reads of notes and reports in the same session.
    served = collections.Counter()
    for f in files:
        pending: dict[str, bool] = {}
        for line in open(f, errors="replace"):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            message = event.get("message") or {}
            if isinstance(message.get("content"), list):
                for part in message["content"]:
                    if not (
                        isinstance(part, dict)
                        and part.get("type") == "toolCall"
                        and part.get("name") == "read"
                    ):
                        continue
                    p = (part.get("arguments") or {}).get("path")
                    cid = part.get("id")
                    if not (isinstance(p, str) and isinstance(cid, str)):
                        continue
                    # the slug itself, as a URI or as a resolved SKILL.md path
                    if re.search(
                        r"(?:skill://|/skills/)aleph-entity-graph(?:/SKILL\.md|$|:)", p
                    ) and in_window(event.get("timestamp")):
                        pending[cid] = True
            if message.get("role") == "toolResult" and message.get("toolCallId") in pending:
                total = (message.get("details") or {}).get("totalLines")
                if isinstance(total, int):
                    served[total] += 1
    print("  documents served under skill://aleph-entity-graph, by line count:")
    for total, count in sorted(served.items()):
        print(f"    {total:4d} lines : {count} read(s)")

    per_session = collections.Counter(r["session"] for r in window)
    busy = {s: n for s, n in per_session.items() if n >= 5}
    with_skill = sum(n for s, n in busy.items() if s in read_aleph_skill)
    without = sum(n for s, n in busy.items() if s not in read_aleph_skill)
    print(f"  sessions issuing >=5 aleph calls    : {len(busy)}")
    print(f"    calls from sessions that read an aleph skill : {with_skill}")
    print(
        f"    calls from sessions that read none          : {without} "
        f"({100 * without / max(1, with_skill + without):.0f}%)"
    )
    print(
        f"  busiest session with no skill read  : "
        f"{max((n for s, n in busy.items() if s not in read_aleph_skill), default=0)} calls"
    )

    print("\n-- dispatches carrying hand-written Aleph rules --")
    rule = re.compile(
        r"READ-?ONLY|facet|limit\D{0,4}0|9999|10,?000|curl|ONLY retrieval surface"
        r"|highlight|entity_id|200 (?:entities|per property)|collection.{0,25}requir",
        re.I,
    )
    dispatches = 0
    rule_lines = rule_chars = 0
    for f in files:
        for line in open(f, errors="replace"):
            if '"task"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            stamp = event.get("timestamp")
            try:
                when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except (AttributeError, ValueError):
                continue
            if not (CUTOFF <= when < END):
                continue
            message = event.get("message") or {}
            if not isinstance(message.get("content"), list):
                continue
            for part in message["content"]:
                if not (
                    isinstance(part, dict)
                    and part.get("type") == "toolCall"
                    and part.get("name") == "task"
                ):
                    continue
                args = part.get("arguments") or {}
                blob = json.dumps(args, ensure_ascii=False)
                if "aleph" not in blob.lower():
                    continue
                dispatches += 1
                tasks = args.get("tasks") or []
                text = (
                    (args.get("context") or "")
                    + "\n"
                    + "\n".join(
                        (t.get("task") or "") if isinstance(t, dict) else str(t) for t in tasks
                    )
                )
                matched = [ln for ln in text.splitlines() if rule.search(ln)]
                rule_lines += len(matched)
                rule_chars += sum(len(ln) for ln in matched)
    print(f"  {dispatches:5d}  dispatches mentioning Aleph")
    print(
        f"  {rule_lines:5d}  rule-bearing lines, {rule_chars:,} chars (~{rule_chars // 4:,} tokens)"
    )
    print("  NOTE: rule-bearing lines only. Whole dispatch contexts are far larger;")
    print("        do not quote total context size as duplicated rule text.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
