# Handoff — architecture deepening, five tasks

Assignments for coding agents run separately. Each task is a self-contained, **behaviour-preserving**
refactor. One agent, one task, one branch, one PR. The author of this file acts as PM and runs the
acceptance gate in `## Acceptance protocol`; do not self-merge.

Source review: `improve-codebase-architecture`, 2026-09-08, against `main @ 1952232`.

---

## Status board

Kept here rather than in a session task list, because a session task list has already been lost once.
Update this table as tasks land; it is the single source of truth for what is done.

| # | Task | State | PR | Notes |
|---|---|---|---|---|
| T3 | Collapse seventeen refusal arms | **ACCEPTED** | #12, merged `a9029e8` | Reviewed retroactively; no substantive findings |
| T1 | Shape the reply on the way out | **ACCEPTED WITH CONDITIONS** | #13, merged `8f1824d` | Deepening proven; four findings open — see T1-FIX |
| T1-FIX | Close the T1 review findings | **ACCEPTED** | #14, merged `3b3059c` | All four findings closed and mutation-verified |
| T1-FIX-2 | Close the two PR #14 regressions | **ACCEPTED** | #14 (same branch), merged `3b3059c` | Both blockers + all five recommendations closed; reviewed by all three pr-review-toolkit agents, one substantive finding found and fixed |
| T2 | Give the bounded-echo rule a module | **ACCEPTED** | #15, merged `9a894fa` | New `echo.py`; four contexts verified byte-identical to `develop`; all three scope traps respected |
| T5 | Collection scope module | **ACCEPTED** | #16, merged `7063627` | New `scope.py`; behaviour byte-identical to `develop` across a 21-refusal/9-spelling probe; reviewed by all three pr-review-toolkit agents, one latent fail-open closed |
| T4 | Lift the transport | **ACCEPTED** | #17, merged `c366624` | New `transport.py`; behaviour byte-identical to `develop` across a 57-outcome probe, and the moved code textually identical modulo four renames; reviewed by all three pr-review-toolkit agents, one critical found and fixed (the live read-only tripwire had stopped asserting) |

**All five tasks are landed and accepted as of 2026-09-09.** `develop` is at `c366624` with
**440 passed, 31 skipped, 5 xfailed**. `AlephClient` went from one 1306-line class holding four
concerns to a 1272-line coordinator over four modules it does not implement: `echo.py` (T2),
`scope.py` (T5), `transport.py` (T4) and the shaping seam (T1), with `server.py`'s seventeen
refusal arms collapsed to one (T3). What remains open is the parked-findings list in
`docs/implementation-notes.md`, which is a queue of behaviour changes, not refactors — each needs
its own change and its own spec question answered.

Out-of-band, not blocking any task: `.github/workflows/ci.yml` still triggers `push: branches: [main]`,
so merges landing on `develop` get no post-merge build; and the `build` job's licence assertion pipes
`tar tzf` into `grep -q` under `pipefail`, which flakes. Both are one-line fixes in the same file, and
pushing them needs SSH (the HTTPS token lacks `workflow` scope).

---

## Baseline — verified, not assumed

Measured on `main @ 1952232` before any task started. If your branch disagrees with any of these,
stop and say so rather than adjusting the number.

| Fact | Value |
|---|---|
| `uv run pytest -q` | **325 passed, 31 skipped** (skips are `tests/live/`, which need `ALEPH_MCP_LIVE_TESTS=1`) |
| MCP tools exposed | **17** |
| MCP resources / templates | **2** static (`aleph://collections`, `aleph://schemata`) + **1** template (`aleph://schema/{name}`) |
| `src/aleph_mcp/client.py` | 1306 lines |
| `src/aleph_mcp/server.py` | 422 lines, 17 identical `except ValueError` arms |
| `tests/test_client.py` | 1682 lines |

**Current baseline, for T2 and everything after it:** branch from **`develop`** (the repo's default
branch), now at **`3b3059c`** with **386 passed, 31 skipped, 5 xfailed**. `main` is the release line
and has not been advanced. The 325/31 figures above are the historical baseline for T1 and T3 only;
362/31 was the baseline for T1-FIX.

The 5 xfails are deliberate and `strict`. They pin the four copy-through positions parked in
`docs/implementation-notes.md` (`get_profile.entities`, `_slim_entityset.entities`, a tag row's
non-string `value`, `_slim_collection`'s `statistics`) so that behaviour cannot change in either
direction without the suite saying so. Fixing any one of them turns its row red as `XPASS(strict)`
and forces the note to be closed — that is intended, not a failure.

There is **no `CONTEXT.md`** and **no `docs/adr/`** in this repo. The spec record is
`openspec/specs/` (`mcp-tool-surface`, `read-only-guard`). Read the requirements your task touches
before you start.

---

## Ground rules — all five tasks

1. **Behaviour-preserving.** No task changes what any requirement asserts. Each changes *where* a
   requirement is enforced. If you believe a task cannot be done without a behaviour change, stop and
   report it — do not proceed under your own judgement.
2. **The whole suite keeps passing**, unchanged in meaning — at the count named in your task's
   header, not the 325 in the historical baseline table. You may rewrite a test whose *structure* the
   refactor obsoletes (e.g. a table that only proved boilerplate was typed correctly). You may not
   weaken or delete an assertion about behaviour. Every such rewrite is called out explicitly in
   your PR body, with the before and after assertion quoted.
3. **Every new test must be shown to fail.** Reintroduce the defect, watch it go red *with the
   symptom you claim it catches*, restore. Paste the red output in the PR body. A test that cannot
   fail certifies nothing, and it will be checked.
4. **No drive-by fixes.** Anything you find outside your task's scope goes as one line in
   `docs/implementation-notes.md` — what, where, why parked — and nowhere else. Two exceptions, both
   of which mean *stop and report*, not *fix*: it blocks your acceptance criteria, or it is a
   security or data-loss defect.
5. **Type-check and lint after every change**, with the commands CI actually runs:
   `uv run --locked ruff check .`, `uv run --locked ruff format --check .`, `uv run --locked mypy`.
   All three clean. Note `[tool.mypy] packages = ["aleph_mcp"]` — CI type-checks `src/` only, not
   `tests/`. Do not widen that as part of your task.
   Gotcha: `ruff format` in this repo also formats Python fenced in Markdown, so a code block
   you add to `docs/` can fail CI. This file was caught by exactly that.
6. **Tier verdict in one line before your first edit**, in the PR body: `Tier <n>: <trigger>`. The
   assessment in each task below is the starting point; overrule it if you can say why.
7. **Do not merge.** Push the branch, open the PR, report. The PM runs the review and the gate.

---

## Verification gates

### Gate A — the tool surface must not drift

Three of the five tasks can silently change what the model sees. The tool descriptions and input
schemas *are* the product here: FastMCP builds them from each tool's docstring and signature.

Save this as a scratch file outside the repo (it is not a repo artifact — do not commit it):

```python
"""Dump the MCP tool + resource surface as canonical JSON, for before/after diffing."""

import asyncio, json, os, sys

os.environ.setdefault("ALEPHCLIENT_HOST", "https://aleph.invalid")
os.environ.setdefault("ALEPHCLIENT_API_KEY", "snapshot-only")

from fastmcp import Client as MCPClient
from aleph_mcp.config import Settings
from aleph_mcp.server import build_server


async def main() -> None:
    mcp_server, client = build_server(Settings())  # type: ignore[call-arg]
    try:
        async with MCPClient(mcp_server) as mcp:
            tools = await mcp.list_tools()
            resources = await mcp.list_resources()
            templates = await mcp.list_resource_templates()
            out = {
                "tools": {
                    t.name: {"description": t.description, "input_schema": t.inputSchema}
                    for t in sorted(tools, key=lambda t: t.name)
                },
                "resources": {str(r.uri): r.mimeType for r in resources},
                "resource_templates": {t.uriTemplate: t.mimeType for t in templates},
            }
    finally:
        await client.aclose()
    json.dump(out, sys.stdout, indent=2, sort_keys=True, ensure_ascii=False)
    sys.stdout.write("\n")


asyncio.run(main())
```

Generate both sides from a throwaway worktree so the baseline comes from pristine `develop`:

```bash
git worktree add /tmp/aleph-baseline develop
(cd /tmp/aleph-baseline && uv run python /path/to/dump_surface.py) > /tmp/surface-before.json
uv run python /path/to/dump_surface.py > /tmp/surface-after.json   # from your branch
diff -u /tmp/surface-before.json /tmp/surface-after.json && echo "SURFACE UNCHANGED"
git worktree remove /tmp/aleph-baseline
```

**Required result for T1, T2, T3, T4, T5: empty diff.** Paste `SURFACE UNCHANGED` in the PR body.

This gate has been proven to fail correctly: dropping one docstring line and one parameter from the
schema produced a diff naming exactly those two tools.

### Gate B — the read-only guarantee holds

For any task touching `readonly.py` or the transport (T2, T4):

```bash
uv run pytest tests/test_readonly.py -q     # baseline: 62 passed
```

and confirm by reading the diff that the allowlist tuple in `readonly.py` gained no entry and lost
no method pin. The method pin is load-bearing: two allowlisted GET paths are also live Aleph write
routes.

### Gate C — a refused call still costs no upstream request

`tests/test_tools.py::ERROR_CASES` asserts `wire.call_count == wire_calls` per tool. That assertion
is about behaviour and survives every refactor below. If your change makes it fail, the change is
wrong, not the test.

---

## Sequencing

```
Wave 1   T1 ──────────────┐        T3  (independent, no file overlap)
Wave 2   └── T2 ──────────┤
Wave 3        └── T5 ─────┤
Wave 4             └── T4 ┘
```

- **T3 shares no file with any other task.** Run it in parallel with anything.
- **T1, T2, T5, T4 all touch `client.py`** and are sequenced to avoid conflicts, cheapest and
  highest-value first. Each later task inherits a smaller, cleaner `client.py`.
- **As of 2026-09-09 T1 and T3 are merged and accepted.** The remaining order is T2 → T5 → T4, and
  it is not optional: T2 moves `_clip`, `_check_collection_id` calls `_clip`, and T5 moves
  `_check_collection_id`. That is a direct overlap, not mere same-file proximity.
- The only work that runs **in parallel** with T2 is `.github/workflows/ci.yml` — the `push:`
  trigger and the `tar tzf | grep -q` pipefail flake. It shares no file with `src/`.
- Two parked defects get *cheaper* after T2 rather than conflicting with it: the `ProxyError`
  sanitisation gap and the unbounded caption both become one-line applications of T2's policy
  module. Queue them straight after, not alongside.

---

# T1 — Shape the reply on the way out, not at ten call sites

**Tier 1**: one module, no observable contract change.
**Files**: `src/aleph_mcp/client.py`, `tests/test_client.py`

### Problem

`derive_caption` and `slim_entity` are pure functions with good unit tests. The bug they can
actually have is not in them — it is at the call site. Ten endpoint methods each independently do
`schemata = await self._schemata()` and pass it into the slimmer. Omit it at one of them and:

- nothing raises,
- no test fails,
- the caption silently falls back to a hard-coded eight-name order, which is right often enough to
  go unnoticed.

Verified: `derive_caption` has five unit tests, and **exactly one** test
(`test_search_derives_captions_from_the_instance_model`) proves the instance model actually reaches
a slimmer — and only on `search_entities`. The other nine paths are unpinned.

The same shape applies to the slimming itself: `slim_entity` is called at ten sites, and
`assert_slim_entity` is applied by hand at roughly fifteen test sites with no tripwire that a *new*
endpoint method is covered — unlike `tests/test_tools.py`, which has
`test_every_tool_has_a_forwarding_case`.

### Required outcome

One exit seam that every entity-returning endpoint method returns through, so an unshaped payload
has no way out of the module. The endpoint methods keep building params and naming their context;
they stop deciding whether to shape.

The exact interface is yours to design — that is the interesting part of this task. Whatever you
pick, it must make "forgot to shape" a **compile-time or test-time failure, not a silent one**.

### Acceptance criteria

- [ ] No endpoint method calls `await self._schemata()` directly; the model fetch happens once,
      behind the seam.
- [ ] A **tripwire test** that fails when an entity-returning method bypasses the seam. Show it red:
      add a method (or unhook an existing one) that returns a raw payload, watch the tripwire fire
      naming that method, restore.
- [ ] All ten previously-unpinned paths now provably shape their replies. A test per path is
      acceptable; a single parametrised test over the ten is better.
- [ ] Gate A: empty surface diff.
- [ ] Gate C: `ERROR_CASES` wire-count assertions unchanged and passing.
- [ ] 325 tests pass; `uv run --locked mypy`, `ruff check .`, `ruff format --check .` all clean.

### Explicitly out of scope

Do not touch the transport, the retry loop, the collection scope, `readonly.py` or `errors.py`.
Do not change any tool docstring. Do not "improve" `derive_caption`'s fallback order.

---

# T1-FIX — Close the four findings from the T1 review

**Tier 2**: touches a safety sink (what upstream material can reach the model) and changes an error
type the tool surface depends on.
**Base branch: `develop`** (8f1824d). **Files**: `src/aleph_mcp/client.py`, `tests/test_client.py`,
`tests/test_tools.py`.

T1 was merged (PR #13) and accepted **with conditions**. Its core deepening is proven: severing the
instance-model plumbing fails 10 tests on `develop` where it failed 0 before. These are the findings
that must close before T2 starts. Every one below was reproduced independently, not read off a diff —
do not re-litigate whether they are real, and do not trust this file over what you observe.

## 1. MUST FIX — `_shape` raises `RuntimeError`, breaking the invariant T3 just established

`src/aleph_mcp/client.py:307`.

`server.py` translates `ValueError` only, so a `RuntimeError` misses the seam entirely. Measured
through a real `MCPClient` round trip against `build_server`:

```
mask_error_details=False
  _shape guard : prefixed=True   guidance_survives=True
      -> Error calling tool 'get_profile': get_profile cannot answer: a defect in this server ...
  T3 refusal   : prefixed=False  message_survives=True
      -> invalid entity_id: must match [A-Za-z0-9._:-]+ (got '../etc/passwd')

mask_error_details=True
  _shape guard : prefixed=True   guidance_survives=False
      -> Error calling tool 'get_profile'
  T3 refusal   : prefixed=False  message_survives=True
```

Two defects in one. The `Error calling tool '<name>': ` prefix is the exact string T3's seventeen
`assert not str(excinfo.value).startswith("Error calling tool")` assertions forbid for every refusal —
so `_shape`'s is the one refusal in the codebase that fails T3's own bar. And under masking the whole
message is replaced, deleting *"Nothing about the call can change this and retrying will not help"* —
the one refusal whose text most needs to survive, because it tells the caller to stop retrying a
defect that can never clear.

Note `mask_error_details` is read **at server construction**, not at call time. Setting it after
`build_server` does nothing — that mistake produced a false negative during review.

**Fix**: raise `ToolError`, not `RuntimeError`. This is not a layering violation: `errors.py` already
raises `ToolError`/`ResourceError` from the client layer (`raise_for_status`, `raise_unreachable`,
`raise_read_only`), and all ten `@_shaped` methods are tools — none is a resource — so the
tool/resource split that motivated `_refusing`'s two flavours does not arise. Update the docstring at
`:295-299`, which currently asserts the opposite of what happens.

**Acceptance**: a masking test for this refusal mirroring `test_a_refusal_survives_error_masking`, and
the existing `startswith` assertion extended to cover it. Show both red first.

## 2. MUST FIX — the classification tripwire's negative half is declared, never verified

`tests/test_client.py:1702` (`NOT_ENTITY_RETURNING`) and `:1865`.

Mutation-verified during review: adding a plausible new entity-returning method on an
**already-allowlisted** path and adding its name to `NOT_ENTITY_RETURNING` ships a real leak with the
full suite green — **362 passed**, and the caller receives `bodyText` plus the whole `RAW_ONLY_KEYS`
housekeeping surface.

The tripwire does fire on an unclassified method, but its message is a bare set inequality naming
neither remedy, and of the two remedies the wrong one is a one-line test edit while the right one
needs a decorator, a `SHAPING_CASES` row and a mock payload. Nothing downstream re-checks the
declaration, because `_shape` never runs on an undecorated method.

`readonly.py`'s allowlist does block a method on a genuinely new path, so the leak needs a method
reusing an allowlisted path — a second view of expand, a raw-entity fetch helper, a paging variant.
That is ordinary, not exotic.

**Fix**: parametrise over `NOT_ENTITY_RETURNING` using the existing `_entities_in` helper
(`tests/test_client.py:1735`), calling each method against a mocked payload carrying `raw_document()`
in the plausible position, asserting the reply contains no entity-shaped dict. Today `SHAPING_CASES`
proves shaped methods shape; nothing proves unshaped methods have nothing to shape.

**Acceptance**: add a method to `NOT_ENTITY_RETURNING` that does return entities, watch the new test
fail naming it, restore.

## 3. SHOULD FIX — a marker that misses the seam leaks as a success

`src/aleph_mcp/client.py:254-266`.

`_shape` is fail-closed on a raw dict left in a reply and fail-**open** on the inverse: an `_Ent` that
never reaches `_shape`. Both markers are plain frozen dataclasses, so the serialiser dumps the field.
Reproduced through the MCP boundary:

```
isError: False
bodyText LEAKED: True     housekeeping 'writeable' leaked: True
payload: {"raw":{"id":"d1","schema":"Document","properties":{"fileName":["m.pdf"],
          "bodyText":["ENTIRE-400-PAGE-DOCUMENT-BODY-XXXX..."]}}}
```

A normal successful-looking result carrying the complete unbounded entity — the exact outcome the
seam exists to prevent, through the one path it does not watch.

**Not live today**: all eight `_Ent` construction sites sit in `@_shaped` methods, and the one
module-level helper that builds markers, `_slim_result`, is called only from `search_entities`,
`match_entity` and `entityset_items`, all shaped. It is a latent trap, and `_slim_result` is exactly
what an author copies when writing a new endpoint.

**Fix**: make the mistake unreachable rather than documented — give `_Ent`/`_AsIs` a
`__get_pydantic_core_schema__` that raises, or assert in `_reply` that the shaped tree contains no
residual marker. Either turns a silent leak into a loud failure.

## 4. SHOULD FIX — `_schemata()` swallows a read-only guard violation

`src/aleph_mcp/client.py:471-478`.

The bare `except Exception` catches more than a slow model. `get_model()` goes through
`_request(..., resource=True)`, which converts a `ReadOnlyViolation` into a `ResourceError` — which
the bare except then eats. Reproduced, one `get_entity` call per row (`'RU-1'` proves the instance
model arrived, `'Acme'` proves it did not):

```
200 healthy                          -> RETURNED OK   caption='RU-1'
401 bad api key                      -> RETURNED OK   caption='Acme'
302 OFF-HOST (read-only guard fires) -> RETURNED OK   caption='Acme'
```

The last row is the problem: `readonly.py`, the module this repo calls its safety boundary, refused a
request trying to leave the configured origin, and the caller got a successful answer. There is **no
logging anywhere in `src/aleph_mcp/`** — verified by grep — so this leaves no trace at all.

Pre-existing, not introduced by T1. But T1 made this the single path by which all ten entity-returning
endpoints obtain the model, so it is now concentrated rather than spread.

**Fix**: catch narrowly. A `ReadOnlyViolation` must never be indistinguishable from "the model was
slow". Letting anything that is not an expected upstream fault propagate would close it.

**Acceptance**: no test in the suite currently makes `/api/2/metadata` fail — every mock returns 200.
Add at least one that pins the intended behaviour for a metadata failure.

## 5. DECISION FOR THE OWNER — not for the implementing agent

`get_profile` is the one place T1 is **not** behaviour-preserving: a profile whose `entities` holds
objects rather than id strings previously returned successfully and now fails the whole call. It is
documented in `docs/implementation-notes.md` as a deliberate fail-closed trade, and that reasoning is
sound — but this handoff required strict behaviour preservation, so it needs explicit sign-off or a
spec change, not a parked note. **Do not change this behaviour as part of T1-FIX.** Leave it, and say
in the PR body that it remains outstanding.

## Out of scope

Everything T2, T5 and T4 own: the bounded-echo module, the collection scope, the transport. Do not fix
the `jsonlib.loads` mislabelling or the `_schemata` negative-caching cost, both parked in
`docs/implementation-notes.md` — the first belongs to T2. Do not delete or rewrite the vacuous
`test_search_derives_captions_from_the_instance_model`; record it and move on.

---

# T1-FIX-2 — Close the two regressions in PR #14

**Tier 2**: one regression changes what the model is told on a fault path; the other silently
removed coverage of a stated repo property.
**Branch: push onto `fix/t1-review-findings`, updating PR #14.** Do not open a second PR — #14 is
open, unmerged and correct in substance; this completes it.
**Files**: `src/aleph_mcp/client.py`, `tests/conftest.py`, `tests/test_client.py`,
`tests/test_tools.py`.

PR #14 closed all four T1 findings, and that holds up: three independent reviews plus the PM gate
mutation-tested every one and each goes red when reverted. Everything below is in the **new**
material. Every measurement here was reproduced by the PM independently — but reproduce them
yourself before changing anything, and if any does not reproduce, stop and say so.

Baseline for this work: `fix/t1-review-findings` @ `1e8e74c`, **380 passed, 31 skipped**.

---

## BLOCKER 1 — the narrowed catch misses `UnicodeDecodeError`

`src/aleph_mcp/client.py:566`

```python
except (httpx.HTTPError, jsonlib.JSONDecodeError):
```

`_request` ends with `jsonlib.loads(body)` where `body` is **bytes**. `json.loads` on bytes runs
`detect_encoding` then decodes, so a body that is not valid UTF-8 raises `UnicodeDecodeError` — a
*sibling* of `JSONDecodeError` under `ValueError`, not a subclass. The tuple does not cover it.

Measured, `/api/2/metadata` answering `200` with `Content-Type: application/json`:

| body | develop | PR #14 |
|---|---|---|
| `b"\x89PNG\r\n\x1a\n"` | DEGRADED, `caption='Acme'` | **HARD FAIL** `UnicodeDecodeError` |
| raw gzip, no `Content-Encoding` | DEGRADED | **HARD FAIL** |
| latin-1 error page | DEGRADED | **HARD FAIL** |
| plain non-JSON UTF-8 | DEGRADED | DEGRADED |

All ten shaped tools fail, and keep failing: `self._model` is cached only on success, so every
later call refetches and fails identically.

The presentation is the worse half. `UnicodeDecodeError` is a `ValueError`, so `server.py`'s seam
converts it and the model receives it **unprefixed and surviving masking**:

```
'utf-8' codec can't decode byte 0x89 in position 0: invalid start byte
```

That is the exact shape of a deliberate, caller-actionable refusal like `invalid entity_id`, but it
names no tool and nothing the caller can change. This is the fault class the whole seam exists to
keep separable.

**Fix**: `except (httpx.HTTPError, ValueError):`. It covers both decode errors and preserves what
the comment argues for — `AttributeError` and `TypeError` still reach the caller.

**Two related gaps in the same arm, both measured:**

- Delete the entire `except (httpx.HTTPError, jsonlib.JSONDecodeError)` arm → **380 passed**. The
  arm most likely to fire on a real instance (a metadata `ReadTimeout`) is tested by nothing. The
  401 test exercises only the `ResourceError` arm.
- Keep every arm and append `except Exception: return None` after them → **380 passed**. The
  narrowing's stated purpose — that a defect in this module reaches the caller instead of silently
  degrading every caption — is pinned by nothing, so a catch-all creeping back is undetectable.

**Acceptance**: a test for a non-UTF-8 metadata body that degrades, a test for a metadata
`ReadTimeout` that degrades, and a test that a genuine module defect (`AttributeError`/`TypeError`)
propagates. Show each red first.

---

## BLOCKER 2 — the conftest default removed the coverage of "a refused call costs no request"

`tests/conftest.py:35`

The default metadata route is registered on the fixture **before** any test body runs, and respx
matches in registration order, so a later catch-all `respx_mock.route()` never sees
`/api/2/metadata`. Fifteen tests build such a catch-all and assert `wire.call_count == 0` under
comments like *"a refused call must cost no request"*.

Measured — the same mutation on both branches, making `_shaped` fetch the instance model *before*
the endpoint issues its own request, which is precisely the invariant `_reply`'s docstring asserts:

| branch | result |
|---|---|
| `origin/develop` | **57 failed**, 305 passed |
| `fix/t1-review-findings` | **1 failed**, 379 passed |

The single survivor catches it only incidentally — `test_guard_runs_on_every_redirect_hop` compares
a list of request paths, so the extra hop shows up as list inequality. Nothing asserts the property
any more.

**Keep the fixture.** It is a genuine improvement: removing it turns 40 tests red with
`AllMockedAssertionError`, proving they had been silently riding the degraded path. The problem is
only that the fixture and the assertions now disagree about what "the wire" means.

**Fix**: make the refusal rows count metadata too — e.g. assert `not metadata_route.called`
alongside `wire.call_count == 0` — or register the default so a test's own catch-all still
pre-empts it.

**Acceptance**: re-run the mutation above on the fixed branch. A refused-call assertion must fail
again. State the new failure count in the PR body.

---

## RECOMMENDED 1 — `_MarkerEscaped` repeats the defect this PR just fixed

`src/aleph_mcp/client.py` marker `__str__`.

`_shape` was correctly moved off `RuntimeError` so its refusal stops being prefixed and stops being
erased under masking. `_MarkerEscaped` is then raised as a bare `RuntimeError`, so:

```
masked=False:  Error calling tool 'get_entity': Error serializing to JSON: _MarkerEscaped: ...
masked=True:   Error calling tool 'get_entity'
```

Prefixed, erased under masking, and `"Error serializing to JSON"` reads as a transient hiccup rather
than a permanent server defect — there is no "nothing about the call can change this" sentence on
this path. A model will retry a permanently broken endpoint, re-issuing the upstream request each
time, because the endpoint's own fetch completes before the seam.

The data half is sound — nine escape routes were probed (dict value, list, tuple, set, dict key,
bare return, lying annotation, `_AsIs`-wrapped, three-deep nesting) and all nine raise with no leak.
This is about actionability, not leakage.

**Fix**: make `_MarkerEscaped` a `ToolError` subclass, or re-raise it as one at the seam, carrying
the same "retrying will not help — report it against aleph-mcp" sentence `_shape` uses. Add the
masked-server test; `tests/test_tools.py:385` builds an unmasked probe only.

## RECOMMENDED 2 — the masking tests cannot detect that masking stopped happening

`tests/test_tools.py:366` and the `masked_server` fixture at `:285`.

Measured, both mutations together: set the fixture's `mask_error_details` to `False` (simulating
FastMCP deprecating the setting to a no-op) **and** revert `_shape` to `RuntimeError` — the exact
defect the test exists to catch → **all 18 masking tests pass**.

This is the same degeneration already identified in `test_a_refusal_survives_error_masking`, copied
into new code. The fixture's `monkeypatch.setattr` catches a *rename*; it does not catch a
deprecation-to-no-op.

**Fix**: one positive control in the masked session — register a probe tool raising
`RuntimeError("SENTINEL-...")` and assert the sentinel is **absent** from the arriving message. It
passes with masking on and fails with masking off, closing all 19 cases at once.

## RECOMMENDED 3 — `NOT_SHAPING_CASES` probes a position five of its methods structurally drop

`tests/test_client.py:1904`

The vacuity guard proves the payload holds an entity *somewhere*, not that it sits where that method
could surface it. For 5 of 10 rows it does not, so those rows can never fail. Moved into each
method's real copy-through field, all five leak a complete `raw_document()` with every blob property
present:

| method | field that actually leaks |
|---|---|
| `get_entityset`, `list_entitysets` | `entities` |
| `entity_tags`, `profile_tags` | a tag row's non-string `value` |
| `get_collection` | `statistics` |

Only the entityset pair is acknowledged in the PR. **Do not fix the underlying passthroughs** — all
three are parked in `docs/implementation-notes.md` as one spec question. Fix only the test, so it
probes the position that can actually leak.

**Fix**: consider asserting on document text rather than entity shape — no blob-property body
anywhere in the reply, with `get_entity_text` opted out — which is position-independent and cannot
be defeated by parking the entity somewhere harmless.

## RECOMMENDED 4 — `_NOT_AN_ENDPOINT` reopens the one-line bypass

`tests/test_client.py:1885`

The new negative-case test exists because "declaring a method entity-free is a claim nothing checks",
and its own comment says the wrong remedy must not be a one-line test edit. `_NOT_AN_ENDPOINT` is a
one-line test edit that satisfies it.

Measured: a plausible `get_entity_raw` on an already-allowlisted path returning the raw payload,
listed in both `NOT_ENTITY_RETURNING` and `_NOT_AN_ENDPOINT` → **380 passed**. (The server layer
still catches it if it is wired up as a tool, so this is a client-gate hole, not an end-to-end leak.)

**Fix**: replace the name allowlist with a property — a member must issue no request when called —
or drop it and give `aclose` a trivial row.

## RECOMMENDED 5 — a comment overstates what one mechanism covers

The docstring says `__get_pydantic_core_schema__` "covers the marker as a declared return type".
It does not, in this architecture: `_shaped` rewrites `__annotations__["return"]` to
`dict[str, Any]`, and every `server.py` tool declares its own return type, so FastMCP never sees a
`-> _Ent`. Removing the hook fails only its own unit test and nothing at the boundary — `__str__`,
i.e. the markers not being dataclasses, is the live mechanism. Correct the comment; keep the hook.

---

## Explicitly out of scope

Do not fix any of these. Each is real, each is recorded, and each is its own change:

- **The unbounded caption.** `slim_entity` bounds every property value to ~500 chars but does not
  bound the caption, so `_omitted_properties: ['indexText']` can be returned beside a caption
  carrying all 100,000 characters of that same blob. An upstream-supplied caption needs no unusual
  ontology at all. Escalated separately by the PM.
- **`get_model` caching `{}`.** A 200 without a `model` key caches an empty ontology permanently;
  `list_schemata` then reports zero schemata with `isError: False`.
- **The cost and silence of the degraded-caption path** — 4 upstream requests and ~7s per entity
  call against a dead metadata route, with no signal in the reply.
- **`get_profile`'s fail-closed behaviour** — still the owner's decision, still untouched.
- Anything belonging to T2, T5 or T4.

Anything else you find goes as one line in `docs/implementation-notes.md`, and nowhere else.

---

# T3 — Collapse seventeen identical refusal arms into one seam

**Tier 1**: one module, no observable contract change.
**Files**: `src/aleph_mcp/server.py`, `tests/test_tools.py`

### Problem

`server.py` is 422 lines. Its only logic is this, written seventeen times:

```python
try:
    return await client.X(...)
except ValueError as e:
    raise ToolError(str(e)) from e
```

An eighteenth arm in `schema_resource` raises `ResourceError` instead. The module is shallow: the
implementation is almost entirely ceremony around the one thing that carries value — the docstrings,
which are the model-facing interface.

`tests/test_tools.py` carries two hand-written 17-row tables (`FORWARDING_CASES`, `ERROR_CASES`)
whose job is partly to prove each copy of the boilerplate was typed correctly.

### Required outcome

One adapter owns the `ValueError → ToolError` / `ValueError → ResourceError` translation. Each tool
body becomes its docstring plus a forwarding call.

### The constraint that makes this delicate

FastMCP builds each tool's schema from the **signature and docstring** of the decorated function.
Any adapter must preserve both exactly — same parameter names, same annotations, same defaults, same
docstring text, character for character. `functools.wraps` alone does not always carry annotations
the way a schema builder needs; verify with Gate A rather than by reasoning about it.

**If Gate A cannot be made to pass, this task fails and should be reported as such.** Do not ship a
version that changes a single character of any tool description. The docstrings are the product.

### Acceptance criteria

- [ ] Gate A: **empty** surface diff. This is the whole task; nothing else matters if this fails.
- [ ] The translation exists in exactly one place. `grep -c 'raise ToolError(str(e))' src/aleph_mcp/server.py`
      returns 0 or 1.
- [ ] `test_every_tool_has_a_forwarding_case` and `test_every_tool_has_a_refusal_case` still pass
      and still enumerate all 17 tools.
- [ ] Gate C: every `ERROR_CASES` row still asserts its wire count, and the
      `assert "validation error" not in str(excinfo.value)` guard is retained — it exists because a
      signature-level rejection never enters the arm under test and can satisfy the expected phrase
      by accident.
- [ ] Show red: remove the adapter from one tool, confirm a test names that tool.
- [ ] 325 tests pass; `uv run --locked mypy`, `ruff check .`, `ruff format --check .` all clean.

### Explicitly out of scope

`client.py` in its entirety. The `INSTRUCTIONS` string. The tool set, the tool names, the resource
set.

---

# T2 — Give the bounded-echo rule a module

**Tier 2**: three modules plus a safety sink. Review is never downgraded here.
**Base branch: `develop` @ `3b3059c`** — **386 passed, 31 skipped, 5 xfailed**.
**Files**: `src/aleph_mcp/client.py`, `src/aleph_mcp/readonly.py`, `src/aleph_mcp/errors.py`,
plus a new module and its tests.

> Re-measured against `develop @ 3b3059c` on 2026-09-09, after T1, T1-FIX and T1-FIX-2 landed.
> `client.py` is now 1594 lines, not the 1306 in the baseline table above. Line numbers below are
> current — but verify before trusting them, and if one disagrees with what you see, believe the
> code and say so.

### Problem

The rule this codebase cares most about — *upstream text reaching the model must be stripped,
quote-neutralised and bounded* — is implemented three times with four caps and three different
behaviours:

| Site | Cap | Refs | Strips controls? | Neutralises `"`? |
|---|---|---|---|---|
| `client.py:155 _truncate` (`_MAX_VALUE_CHARS`, `:74`) | 500 | 4 | no | no |
| `client.py:134 _clip` (`_MAX_ECHO_CHARS`, `:131`) | 120 | 2 | relies on the caller's `!r` | no |
| `readonly.py:92 _describe` (`_MAX_TARGET_CHARS`, `:89`) | 120 | 2 | yes | n/a (also drops userinfo and query) |
| `errors.py:170 _as_quoted_data` (`_MAX_UPSTREAM_CHARS`, `:137`) | 200 | 3 | yes | yes |

`errors.py:184` also holds a private `_truncate(s, n)` that only `_as_quoted_data` uses — a fifth
implementation of the same idea, and a different signature from `client.py`'s `_truncate`.

The comments already cross-reference each other in prose — `client.py:130` says *"…reaching the
model is capped — see `errors.py:_as_quoted_data` and `readonly.py:_describe`"*. A rule that has to
be restated in three comments has no home.

There is already a **fourth path with no truncator at all**: the `httpx.ProxyError` finding parked
in `docs/implementation-notes.md`, where proxy-authored text reaches the model past all three
helpers.

### Three message paths added since this task was written — and why they are NOT call sites

T1 and T1-FIX added three new model-visible messages. Check them yourself, then leave them alone:

- `server.py:109` — the escaped-marker refusal at the `_refusing` seam
- `client.py:314` — the marker's `__str__` refusal
- `client.py:391` — `_shape`'s raw-entity refusal

All three are **server-authored end to end**. They interpolate only an endpoint or class name, both
of which this repo chooses, and quote nothing from upstream — that was verified when they were
written and re-verified for this refresh. They are refusals, not echoes, so they do not belong
behind the new module. Naming them here so you do not have to wonder, and so a reviewer can see the
question was answered rather than missed.

### Required outcome

One module owning the rule. Its interface takes the text and a **named policy**; the caps stay
different per context, because they are different for real reasons — a facet bucket label at 500
chars is data the analyst wants, an error echo at 200 chars is an aid to the operator. Flattening
them to one number is a behaviour change and is **not** what this task asks for.

Every existing call site renders through the new module.

### Acceptance criteria

- [ ] All four helpers replaced by calls into one module; `client._truncate`, `client._clip`,
      `readonly._describe` and `errors._as_quoted_data` are gone, along with `errors.py`'s private
      `_truncate`.
- [ ] Each context keeps its current cap and its current behaviour, exactly as tabulated above. A
      test per policy pinning the cap and the stripping behaviour, including the two that have no
      equivalent test today (`client._truncate`, `client._clip`).
- [ ] Show red for each new test: widen the cap by one character, confirm the test fires.
- [ ] Gate A: empty surface diff, baselined from `develop`.
- [ ] Gate B: `readonly.py`'s allowlist tuple unchanged; `tests/test_readonly.py` green
      (baseline: 62 passed).
- [ ] `tests/test_errors.py::test_the_payload_cannot_close_the_quoted_region_or_carry_control_characters`
      still passes unmodified.
- [ ] **386 passed, 31 skipped, 5 xfailed** — the xfails stay xfailed. If one turns `XPASS(strict)`
      you have changed a parked behaviour; stop and report rather than adjusting the marker.
- [ ] `uv run --locked mypy`, `ruff check .`, `ruff format --check .` all clean.

### Explicitly out of scope

**Do not fix the `ProxyError` finding.** It is real, it is recorded, and fixing it here would couple
an unrelated behaviour change into a refactor the PM has to accept or reject as a unit. Note in the
PR body that the new seam makes it a one-line fix; leave it parked.

**Do not bound the caption.** `slim_entity` bounds every property value but not the caption, so a
reply can carry `_omitted_properties: ['indexText']` beside a 100,000-character caption holding that
same blob — re-confirmed live on `develop @ 3b3059c`. This will look like your task: it is an
unbounded upstream string, and you are building the module that bounds upstream strings. It is
nevertheless a **behaviour change to a tool's output**, which this refactor is not. It is escalated
and queued to run straight after T2, precisely because your module turns it into a one-line policy
application. Taking it now converts a reviewable refactor into a mixed diff.

Do not change any cap. Do not touch the transport, the shaping seam, or the collection scope. Do not
fix `get_model` caching a non-dict `model`, also parked.

---

# T5 — Make the collection scope a module that renders itself

**Tier 2**: a silently-wrong scope is the data-integrity failure the spec exists to prevent.
**Base branch: `develop` @ `956dedd`** — **408 passed, 31 skipped, 5 xfailed**.
**Files**: `src/aleph_mcp/client.py`, `tests/test_collection_scope.py`, plus a new module.

> Re-measured against `develop @ 956dedd` on 2026-09-09, after T1, T1-FIX, T1-FIX-2 and T2 landed.
> `client.py` is 1580 lines and `tests/test_collection_scope.py` is 506, not the figures in the
> historical baseline table. Line numbers below are current — verify before trusting them, and if
> one disagrees with what you see, believe the code and say so.

### Problem

Collection scope is the hottest concept in this codebase's history — `require-explicit-collection-scope`,
a dedicated 506-line test file — and `openspec/specs/mcp-tool-surface` names it. It exists as
scattered parts of `client.py`, which also does HTTP:

| Part | Line |
|---|---|
| `_COLLECTION_ID` pattern | 93 |
| `ALL_COLLECTIONS` sentinel | 100 |
| `Scope` type alias | 106 |
| `MAX_SCOPE_COLLECTIONS` | 112 |
| `_check_collection_id` | 127 |
| `_foreign_ids` cache | 532 |
| `_resolve_collection_id` | 831 |
| `_resolve_collection_scope` | 902 |

Seven call sites depend on them — `_resolve_collection_id` from `get_collection` (828),
`list_entitysets` (1341), `xref_results` (1406) and twice inside `_resolve_collection_scope`
(919, 956); `_resolve_collection_scope` from `search_entities` (1024) and `match_entity` (1232).

And three sites each re-derive how a resolved scope becomes a query parameter:

- `client.py:1044` — `filter:collection_id`, one per id (search)
- `client.py:1240` — `collection_ids`, one per id (match)
- `client.py:1340` — `filter:collection_id`, single id (entitysets)

Two distinct wire spellings exist today, so the seam is real, not hypothetical.

### What T2 changed here, and what you must preserve

`_check_collection_id` no longer clips its own echo. It now calls
`render(text, COLLECTION_ECHO)` from `src/aleph_mcp/echo.py`, because on one path the value is
upstream text — the `id` read out of a `filter:foreign_id` lookup — and this repo bounds every
upstream string that reaches the model.

Carry that call into the new module **unchanged**: same policy, same cap, same `!r` around it. The
`!r` is load-bearing and the comment says why — `COLLECTION_ECHO` deliberately does not strip
control characters because `!r` escapes them. Dropping the `!r` while keeping the policy would
silently unstrip them.

### Required outcome

One module owning parse, resolve, cache and rendering. Parse is pure and refuses without I/O — that
property already holds and is load-bearing (the spec promises a refused call costs no lookup), so
preserve it and make it testable without a mocked upstream.

### Acceptance criteria

- [ ] Parse-level refusals (empty, blank, `"*"` mixed with ids, over `MAX_SCOPE_COLLECTIONS`,
      non-numeric form) are tested **without `respx`**. That they need no mocked upstream is the
      evidence the seam is in the right place. For scale: the current file has 23 test functions
      and 57 `respx_mock` references, so almost everything is mocked today.
- [ ] The three renderings are methods on the resolved scope, not open-coded at call sites.
- [ ] `_check_collection_id`'s `render(..., COLLECTION_ECHO)!r` survives intact. Show it: feed a
      120+ character upstream id containing a control character and a quote, and assert the message
      is bounded and escaped exactly as it is on `develop`.
- [ ] Every requirement in `openspec/specs/mcp-tool-surface` about collection scope still holds,
      unchanged. Quote each one you checked in the PR body.
- [ ] The order-preserving dedup on **both** the input spellings and the resolved ids is preserved —
      a numeric id and a foreign_id naming the same collection must still collapse to one filter.
- [ ] The resolution deadline and the "only a verified hit is cached" behaviour are preserved.
- [ ] Show red: break the resolved-id dedup, confirm a test fires.
- [ ] Gate A: empty surface diff, baselined from `develop`.
- [ ] Gate C: `ERROR_CASES` wire counts unchanged — several of them are collection refusals, and
      "a refused call costs no upstream request" is exactly what a scope resolver can break.
- [ ] **408 passed, 31 skipped, 5 xfailed** — the xfails stay xfailed. If one turns
      `XPASS(strict)` you have changed a parked behaviour; stop and report.
- [ ] `uv run --locked mypy`, `ruff check .`, `ruff format --check .` all clean.

### Explicitly out of scope

Any change to what scope values are accepted or refused. This is a move, not a redesign of the
contract.

The transport and the retry loop — those are T4's, and `_resolve_collection_scope`'s deadline sits
close enough to them to be tempting.

Do not fix any of these parked findings, all recorded in `docs/implementation-notes.md`:

- **`get_schema`'s unbounded echo.** `client.py` builds `"Did you mean one of: …"` from upstream
  ontology keys with no cap and no policy — reproduced at 20,112 characters with `ESC`, `NUL`,
  `U+202E` and a raw quote intact. It is the nearest neighbour to your task and it is **not yours**:
  it needs a new policy and a bound on a joined list, which is a behaviour change to a tool's output.
- The unbounded **caption**, `get_model` caching a non-dict `model`, and the `ProxyError`
  sanitisation gap.

Anything else you find goes as one line in `docs/implementation-notes.md`, and nowhere else.

---

# T4 — Lift the transport out of AlephClient

**Tier 2**: a safety sink — the read-only allowlist hook moves. Largest diff of the five.
**Files**: `src/aleph_mcp/client.py`, `tests/test_client.py`, plus a new module.

### Problem

`AlephClient` is 1306 lines holding four concerns. Roughly 190 of them are a genuinely deep
transport that belongs behind a one-method interface:

- the retry budget, charged once across sleep and connect time
- the separate connect cap (`MAX_CONNECT_SECS`)
- the streaming size ceiling (`_read_bounded`, which must refuse *during* iteration because httpx
  content-decodes as it goes)
- the read-only allowlist event hook
- status → MCP error translation

`tests/test_client.py` is 1682 lines mixing retry-budget and gzip-bomb cases with payload-shape
cases, because there is no seam that lets either be tested alone.

### The design question that makes this a seam and not a file split

`search_entities` reaches back through the boundary: it catches `ResponseTooLarge` and re-asks with
a halved page, up to `MAX_SEARCH_SHRINKS` times, under its own deadline. Two options:

1. the shrink moves inside the transport as a page-shrinking request, or
2. the seam exposes that failure by type and the caller keeps the loop.

**Decide deliberately and write the reasoning in the PR body.** Picking one without arguing it is
the failure mode for this task.

### Acceptance criteria

- [ ] Transport behaviour is provably unchanged: the retry budget, the connect cap, the streaming
      ceiling, the `Retry-After` handling and the buffer-clearing on refusal all still hold.
      The buffer clear is not cosmetic — it was measured at 4.16× resident growth without it.
- [ ] At least one transport test that needs **no Aleph-shaped payload**. That is the evidence the
      seam is real.
- [ ] Gate B: the allowlist tuple in `readonly.py` gains no entry and loses no method pin. Read the
      diff and say so explicitly.
- [ ] `tests/test_readonly.py::test_refresh_is_emitted_only_by_get_collection` still passes — it is
      the tripwire on the one named exception to "asks the server only to answer"
      (`openspec/specs/read-only-guard` line 150).
- [ ] The `_monotonic` indirection that lets tests advance a fake clock survives, or is replaced by
      something that also lets a test move the clock. A retry-budget test that cannot move the clock
      is blind to the term that dominates it.
- [ ] Show red: break the budget charge on the connect path, confirm a test fires.
- [ ] Gate A: empty surface diff.
- [ ] The full suite passes at the count in this task's header. **That header is refreshed when
      the task is scheduled — if it still says 325, it has not been refreshed and you should say
      so before starting.** `uv run --locked mypy`, `ruff check .`, `ruff format --check .` clean.

### Explicitly out of scope

Do not fix the two transport findings parked in `docs/implementation-notes.md` (the `ProxyError`
sanitisation gap, the TLS-failure retry with wrong advice) or the uncharged response-path budget.
All three are real; all three are behaviour changes; all three belong in their own change. Note in
the PR body which of them the new seam makes cheaper.

---

## Acceptance protocol

Submit: a pushed branch, an open PR, and a PR body containing —

1. `Tier <n>: <trigger>` — your verdict.
2. The `SURFACE UNCHANGED` line from Gate A.
3. Test counts before and after.
4. For **every** new test: the command you ran to make it red, and the red output.
5. Any test you rewrote, with the before and after assertion quoted, and why the rewrite does not
   weaken it.
6. Anything you parked in `docs/implementation-notes.md`.

**You run the review fleet, not the PM.** Before submitting, run
`pr-review-toolkit:code-reviewer` and `pr-review-toolkit:silent-failure-hunter` on your diff, plus
`pr-review-toolkit:pr-test-analyzer` if you added tests. Report every finding in the PR body with
its resolution — fixed, or dismissed with a reason. A finding you dismissed is not a problem; a
finding you did not mention is.

The PM then, independently — and **does not re-run those three agents**, because you already did,
and running them twice doubles the wall-clock wait for the same output:

- Re-runs the full suite from a clean checkout of the branch. Your reported count is not evidence.
- Re-runs Gate A from a pristine `develop` worktree.
- **Runs a differential** against `develop` on the behaviour your task was supposed to preserve —
  same inputs both sides, outputs compared. This is the check your own review cannot make for you,
  because it needs the before-state.
- **Re-derives at least one red-test claim** by reintroducing the defect and watching it fail. A
  test asserted to catch something, that does not, is the single failure mode this protocol exists
  to catch.
- Reads the diff for scope creep against the "explicitly out of scope" list, and spot-checks the
  findings you reported rather than rediscovering them.

Findings come back to you to fix or dismiss with a reason. Nothing merges until they are closed.
