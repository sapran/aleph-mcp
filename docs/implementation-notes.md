# Implementation notes

Findings recorded during other work, kept out of the change that surfaced them. An entry leaves
this file when it becomes a spec requirement or is fixed — not when someone remembers to tidy up.

Triaged 2026-09-10 against `develop @ b46b52d`: all 35 open claims were re-checked in the live
tree, close relatives merged into the change that would close them, and two retired. Thirty-three
survived, as fourteen entries. Entries are ordered by the work plan below; the numbering is the
priority order, not an id. Item 1 of that plan — the metadata path — was closed by
`harden-metadata-path` on 2026-09-10, and item 1 of the renumbered plan — transport failure
classification — by `classify-transport-failures` the same day. The plan and the sections below
are renumbered after each, so twenty-nine claims across twelve entries remain.

## Work plan

1. Bound and neutralise the ontology echo — upstream schema names reach the model uncapped.
2. Charge and account the response path — a 502 costs 16 requests and names the wrong cause.
3. Guard the scope resolver's upstream shapes — untranslated errors, confident wrong diagnosis.
4. Give refusals a type — a dead upstream is reported as a bad argument.
5. Make the licence gate able to fail — it passes with the project's own LICENSE deleted.
6. Answer the entity-shaped spec question — four copy-through slots, one decision, five xfails.
7. Extend the tool path's guarantees to resources — a `resource()` factory and a wider walk.
8. Close echo.py's enforcement gaps — an inline policy escapes both guards.
9. Give `get_entity_text` a derived caption.
10. Close the tests that cannot fail — four checks that certify nothing.
11. Decide the private-sibling references — the publication deadline has already passed.
12. Correct three pieces of stale prose (Tier 0).
---

## 1. The ontology echo is unbounded and un-neutralised

**`get_schema` echoes upstream schema names into a refusal.** `client.py:597` builds
`f"Did you mean one of: {', '.join(close[:10])}?"` from the keys of `model["schemata"]`, which is
upstream text from `/api/2/metadata` — no cap on each name, no `!r`, and no `echo` policy, while
`name!r` beside it is caller input and *is* escaped. Found by security review during T2 and
reproduced against pristine `develop @ 01a48c4`, so it predates that change: a schema key carrying
`ESC`, `NUL`, `U+202E` and a raw `"` arrives in the message with all four intact, and one
20,000-character key produced a 20,104-character refusal. It reaches the model through
`aleph://schema/{name}`, which `server.py`'s `_as_resource_error` seam forwards with `str(e)` — so
unprefixed and surviving `mask_error_details`, the shape this repo reserves for caller-actionable
refusals. Needs its own policy (a plain strip, since the names are interpolated without `!r`) plus
a bound on the joined list rather than only on the count. Related and lower: `list_schemata`
(`client.py:583`) returns `sorted(schemata)` — every upstream key, unbounded in count and length —
into `aleph://schemata`, bounded only by `MAX_RESPONSE_BYTES` and carrying no `_provenance` label.
Behaviour change to a tool's output, so kept out of T2.

## 2. The response path is neither charged nor accounted

**Only the connect path charges its elapsed time to the retry budget.** `transport.py:169` charges
the connect elapsed; the response path charges only `delay` (`transport.py:174`), so a slow 429/5xx
round trip is uncharged and `max_retries` slow responses can exceed `timeout_secs` in total. The
connect path had to be charged because a connect can burn the whole connect phase without ever
sleeping; the same one-line charge was never extended.

**A non-2xx whose body is over the ceiling is reported as a ceiling refusal, never as the status.**
`_read_bounded` (`transport.py:160`) runs before `raise_for_status` (`transport.py:179`) and does
not look at `resp.status_code`, so a 502 with a >25 MiB body raises `TooLargeToolError` and the 502
is discarded. Measured identical on `develop` and the T4 branch: a 502 with a plain body costs 4
requests and says "unexpected HTTP 502"; a 502 with an oversized body costs **16** requests — the
shrink loop re-asks four times, each paying four transport retries because 502 is in
`_RETRY_STATUS` — and tells the model to narrow its query, never that the instance is failing. Only
`search_entities`' deadline bounds it. Related inaccuracy: the comment at `transport.py:41` claims
the error path "has its own, much smaller bound"; the 64 KiB `_MAX_ERROR_BODY_BYTES` in
`_upstream_detail` bounds only what is *quoted*, and above the ceiling the error path is never
reached at all. Fixing it changes a refusal message, so it is a behaviour change.

## 3. The scope resolver mishandles three upstream shapes

All three in `scope.py`, adjacent lines, one change.

**A non-list `results` from the collection listing escapes the `except ValueError` seam.**
`scope.py:312`. The `isinstance(results[0], dict)` guard covers a body that arrives as a list or a
scalar, because `Transport.request` wraps a non-dict body as `{"results": <body>}` — but an Aleph
*dict* body whose own `results` key is not a list reaches `results[0]` on a truthy non-list.
Measured on both `develop` and the T5 branch, byte-identical: `{"results": {"a": 1}}` raises
`KeyError`, `{"results": 5}` and `{"results": true}` raise `TypeError`. `server.py` translates
`ValueError` only, so these reach the model untranslated rather than as a legible refusal.

**"no collection with foreign_id X" absorbs an upstream malfunction.** `scope.py:321-325`. Any
lookup payload without a usable `results[0]` — including `{"status": "error"}` with no `results` key
at all, and `{"results": [null]}` — is reported to the model as an authorisation-or-existence
problem naming `list_collections`. A proxy, an SSO interstitial or an unfamiliar Aleph version
therefore produces a confident wrong diagnosis and a dead-end next step. Fail-closed, so no wrong
rows are returned.

**A single-element `["*"]` is refused with the wrong reason.** `scope.py:150` fires the mixed-scope
message — "cannot be combined with named collections" — for a list that names no other collection.
The scalar `"*"` is accepted at `scope.py:141`. Unchanged from `develop`, untested anywhere.
Correcting it changes a refusal message.

## 4. Bare `ValueError` is the wrong refusal channel, in both directions

Both halves close with one type: a dedicated `Refusal(ValueError)` raised at the client's own
refusal sites and caught in place of bare `ValueError` — the pattern `errors.py` already sets for
`ResponseTooLarge`.

**Too wide.** `Transport.request` (`transport.py:180`) decodes the body with an unguarded
`jsonlib.loads`. `json.JSONDecodeError` and `UnicodeDecodeError` are both `ValueError` subclasses,
so a 2xx whose body is not JSON — an HTML maintenance page, a proxy interstitial, a truncated body
— reaches the model as a refusal reading `Expecting value: line 1 column 1 (char 0)`,
indistinguishable from "you passed a bad id". The rational reply to a refusal is to change arguments
and retry, against an upstream that is down. Run-verified identical on `main @ 1952232`;
`errors.py:74` already guards the analogous connect case.

**Too narrow.** The refusal seam wraps the whole tool body (`server.py:132`), where the arms it
replaced wrapped only the `await client.X(...)` call. Equivalent today — every body is one
forwarding call — but a future in-body `int()`, `datetime.fromisoformat()` or nested `json.loads`
would be relabelled as a client refusal with nothing to catch it.

## 5. The licence gate cannot fail

Both in `.github/workflows/ci.yml`, the `build` job's licence step; one change. (The SIGPIPE race
in the same step is fixed — see Retired.)

**The assertions are unanchored, so a vendored LICENSE keeps them green while the project's own is
gone.** `grep -q 'licenses/LICENSE'` is a bare substring against the whole `unzip -l` listing, so
`aleph_mcp/vendor/licenses/LICENSE` satisfies it; `grep -q '/LICENSE$'` matches a member at any
depth, so `<pkg>/src/aleph_mcp/vendor/somedep/LICENSE` satisfies it. What the step means to assert
is `<name>-<ver>.dist-info/licenses/LICENSE` for the wheel and a root-level `LICENSE` for the sdist.
Verified by rebuilding both artefacts with the real licence deleted and a third-party one planted
deeper: **both the old and the new step exit 0** and print "licence expression, header and file all
present". That is precisely the case the step exists to catch — hatchling silently drops the licence
file and a bundled dependency's licence hides it. The fix is to anchor them:
`'\.dist-info/licenses/LICENSE'` for the wheel and `-E '^[^/]+/LICENSE$'` for the sdist. Today the
repo has exactly one LICENSE, so nothing would go red.

**It names the wrong cause when the check cannot run, and prints no listing when it fails.** A
here-string redirection that fails (unwritable `$TMPDIR`) or a `grep` exiting >1 lands in the same
`|| { ... }` arm as a genuine miss, so the log says "the sdist ships no LICENSE" and sends the
reader to rebuild an archive that is fine; and neither arm prints the listing it already holds,
which is the first thing anyone debugging a packaging regression wants. Also, two artefacts in
`dist/` fail cryptically (`tar: <second>: Not found in archive`, or a two-line `$wheel` that breaks
`unzip -p`) — unreachable in CI, where the checkout is fresh and `uv build` is the only writer, but
it bites anyone running the step locally against a dirty `dist/`.

## 6. Four aggregation slots are copied rather than rebuilt — one spec question

`get_profile.entities`, `_slim_entityset.entities`, a tag row's `value`, and
`_slim_collection(full=True).statistics` are one decision about what counts as entity-shaped, not
four refactors. Since T1-FIX-2 each is pinned by a `strict` xfail row in `NOT_SHAPING_CASES`
(`tests/test_client.py:1637-1669`), so the behaviour cannot change without the suite saying so, and
fixing any of them forces this note to be closed.

- **`get_profile` passes its `entities` field through unshaped** (`client.py:980`). It holds id
  strings in every fixture and on the live instance, so nothing leaks today, but the "binds every
  entity-shaped value in a response" requirement in `openspec/specs/mcp-tool-surface` would be
  violated by an instance that serialised objects there. Since T1 this fails *closed*: `_shape`
  refuses an unmarked entity-shaped dict. **Decided 2026-09-10: accepted as-is, and shipped as a
  documented behaviour change in 0.3.0.** The failure only occurs on an instance that serialises
  `entities` as objects, which no fixture and no tested instance does; the leak it prevents would be
  silent and unbounded. The note stays open because the *availability* half is unaddressed: on such
  an instance the tool does not degrade, it stops answering, and the message blames this server for
  an upstream shape. Marking the field so the seam skips it would restore the leak; shaping the
  objects properly is the fix that makes the question disappear.
- **`_slim_entityset` copies upstream `entities` verbatim, and nothing fails closed there.**
  `get_entityset` and `list_entitysets` pass that field straight through exactly as `get_profile`
  does — but both sit outside T1's shaping seam, so the `_shape` guard never runs and the protection
  above does not extend to them.
- **`_slim_tags` copies a tag row's non-string values through.** `entity_tags` and `profile_tags`
  truncate a row's *string* values and pass every other value on unchanged, so an entity object as a
  row's `value` arrives with all five blob properties intact. Aleph returns `{field, value, count}`
  rows there, so this needs the same upstream contract change and leaks nothing today.
- **`_slim_collection(full=True)` copies `statistics` verbatim.** `get_collection` returns whatever
  that block holds, unread and unbounded; `list_collections` does not, because it slims with
  `full=False`.
- **An upstream `_note` key makes `get_entityset` return the whole unslimmed payload.**
  `client.py:1164` short-circuits the slimmer on `if payload.get("_note")`, a branch written for
  the server-authored profile-redirect reply — but the test is on the *decoded upstream body*, so
  an instance or an on-path proxy that adds one `_note` key to a 200 gets the entire payload back
  verbatim, bypassing `_slim_entityset`'s fixed key set, the `bodyText` strip and the 500-char
  property cap. Executed during review of `harden-metadata-path`: with the key present a hostile
  note, an unknown upstream key and a 400-character `bodyText` all reached the caller; without it
  the reply was slimmed and the `bodyText` dropped. A different mechanism from the `entities`
  copy-through above, and unexercised by the suite — no test sends a 200 carrying `_note`. It also
  becomes sharper if `get_entityset` is ever `@_shaped`, which is the natural fix for the slot
  above: upstream text would then land in `_reply`'s existing-note composition. Fix is to key the
  short-circuit on something upstream cannot set. Pre-existing and outside that change's scope.

## 7. The resource path lacks the tool path's guarantees

Three findings, closed by a ~4-line local `resource(uri, **kw)` factory mirroring `tool`, plus a
wider walk in `find_marker`.

**Resources have no counterpart to the fused `tool` helper.** `@mcp.resource` is still reachable raw
(`server.py:400`, `:405`), and `schema_resource`'s translation is a hand-applied decorator
(`server.py:411`) nothing enforces. A future *parameterised* resource would silently regress to
FastMCP's `Error reading resource '<uri>': ` wrapping, and the decorator order is load-bearing but
fails silently (`@_as_resource_error` above `@mcp.resource` imports, registers and serves the
untranslated message). `collections_resource` and `schemata_resource` cannot raise `ValueError` at
all, so decorating them now would be dead code.

**The marker guard covers every tool but only one of three resources.** `find_marker` runs inside
`_refusing`, so `collections_resource` and `schemata_resource` return without it. Inert today: both
call unshaped client methods that build no markers. It becomes real only if a resource is ever
pointed at a `@_shaped` method.

**`find_marker` does not traverse tuples, sets or dict keys.** `client.py:370-382` walks dicts by
value and lists by item only. No client method builds a tuple, a set or a non-string key into a
reply, so nothing reaches those branches today, and the markers' own serialisation refusal still
fires there — the outcome degrades to the pre-T1-FIX-2 message rather than leaking.

## 8. echo.py's two enforcement gaps

**A policy built inline at a call site escapes both guards.** `test_every_policy_has_a_cap_row`
(`tests/test_echo.py:59`) enumerates `vars(echo)`, so it sees only module-level policies declared in
`echo.py`. `render(v, replace(PROPERTY_VALUE, max_chars=77))` at a call site is invisible to it and
to every cap row, which defeats the "each site asks for the treatment by name" property the module
exists to establish. All seven call sites today name one of the four policies, so this is a missing
enforcement, not a live defect. Closing it means either forbidding non-module policies at runtime or
asserting the seven call sites against the four names.

**`echo.COLLECTION_ECHO` leaves control characters to its call site's `!r`.** The behaviour the four
helpers had, preserved deliberately rather than a new gap. `scope.py:81` is the only caller and
formats the result with `!r`, which escapes controls — so the policy does not strip them itself. A
second caller that interpolated the rendering plainly would put upstream control characters into a
model-visible message. Recorded because the coupling is now between two files rather than inside one
function. Closing it means either stripping in the policy (a behaviour change to the existing
message) or asserting the `!r` at the call site.

## 9. `get_entity_text` derives no caption

`client.py:1188` reads `entity.get("caption")` straight off the payload, where every slimmed path
calls `derive_caption`. Live Aleph sends a null caption, so this is the one tool that can return
`caption: null` for an entity the other tools would have captioned. Found during T1; fixing it
changes a tool's output and so is a behaviour change, not a refactor.

## 10. Four checks that certify nothing

One purely-test change closes all four.

- **`test_search_derives_captions_from_the_instance_model` cannot fail**
  (`tests/test_client.py:1056`). Its mocked model declares the caption order `["name"]`, which is
  also the first entry of `_CAPTION_FALLBACK`, so it passes whether or not the instance model
  reaches the slimmer. Superseded, not load-bearing: T1's
  `test_every_entity_returning_method_shapes_its_reply` covers the same path with a discriminating
  model. Delete or strengthen.
- **The `MAX_SCOPE_COLLECTIONS` boundary is unpinned.** Only `MAX + 1` is tested
  (`tests/test_scope.py:91`); changing `>` to `>=` at `scope.py:161` — which would refuse a
  legitimate ten-collection scope — passes the whole suite. Related and also unpinned: the dedup runs
  *before* the bound, so eleven spellings collapsing to ten are accepted. One row in the existing
  parametrised table.
- **`AlephClient.aclose` delegation is untested.** Making it a no-op leaves the whole suite green, on
  `develop` (where it closed `_http` directly) as well as after T4 (where it delegates to
  `Transport.aclose`).
- **`verify_tls` has no test anywhere.** Zero hits across `tests/`, so nothing pins that
  `ALEPH_MCP_VERIFY_TLS` reaches the httpx client at all. Sharpened rather than closed by
  `classify-transport-failures`: a TLS refusal now names that setting to the operator, so the
  message is wrong in a new way if the setting never reaches the client.

## 11. A public repo still points at private siblings

The publication this was to be decided before has happened — 0.3.0 shipped from a public repo on
2026-09-10 — so this is now a live defect rather than a pending decision.

**Non-public sibling tools are named outside the README.** The open-source readiness branch removed
the dead `../aleph-coldbackup` / `../datashare-mcp` links from `README.md`, but the same tool is
still named in `src/aleph_mcp/server.py:68` (server instructions, so a model sees it),
`src/aleph_mcp/config.py:19` (comment) and
`plugins/aleph/skills/aleph-entity-graph/SKILL.md:64`. `tests/test_tools.py` asserts on the
instructions string, so changing it is not free.

**`openspec/config.yaml` declares a private remote.** The `acordia` reference
(`openspec/config.yaml:13`) points at `https://github.com/sapran/acordia-agents.git`, which is
private; `acordia` is also named across the specs, the archived changes and
`plugins/aleph/README.md`. `openspec doctor` or a register attempt hits a 404 on a repo a
contributor cannot see. The declaration is deliberate and documented, so removing it is a design
decision, not a cleanup.

## 12. Three pieces of stale prose (Tier 0)

- **`openspec/config.yaml`'s layout paragraph is three modules stale**
  (`openspec/config.yaml:23-26`). It lists `server.py`, `client.py`, `readonly.py`, `config.py` and
  `errors.py` and names none of `echo.py` (T2), `scope.py` (T5) or `transport.py` (T4). No spec
  assertion depends on it.
- **Comment drift naming the structure T3 deleted.** `scope.py:320`,
  `tests/test_collection_scope.py:339` and `:454` still say "no tool's `except ValueError`
  translates". The claims stay true of the single seam, but send a reader looking for per-tool arms
  that no longer exist.
- **`pyproject.toml` sets `line-length = 100` while `[tool.ruff.lint]` ignores `E501`**
  (`pyproject.toml:64`, `:69`), so line length is enforced only by `ruff format`, never by
  `ruff check`. Harmless; noted because the contributor-facing constraint reads as if `ruff check`
  enforces it.

---

## Retired

- Transport failures being classified by the wrong axis — both claims (attacker-authored
  `ProxyError` text reaching the model unsanitised, and a TLS verification failure retried four
  times with reachability advice) are now three requirements in
  `openspec/specs/mcp-tool-surface`, and the partition is verified by a test that walks
  `httpx.TransportError`'s subclasses from the live module rather than listing them.

- The version being written in three places with nothing checking they agree — which shipped
  0.1.4 to every marketplace user as 0.1.2, because the *catalog* version is what drives
  change detection in `omp plugin upgrade`. **Fixed** by `tests/test_packaging.py`, which
  asserts the three declared versions equal `aleph_mcp.__version__`.
- The `$` anchor letting `entity_id="e1\n"` through, and `entityset_id=".."` normalising away to
  a different endpoint. **Fixed** by `fix-id-validation-anchors`; the validators now use
  `re.fullmatch`, as the allowlist always has.
- The guard matching a decoded path while the transport sends the encoded one. **Specified** by
  `baseline-read-only-guard` as a requirement that carries its own invalidating condition, with
  `test_id_charset_excludes_percent` as the tripwire: if `%` is ever added to the accepted id
  charset, that test fails and the guard must move to `raw_path`.
- `GET /api/2/collections/{id}?refresh=true` asking Aleph to recompute statistics. **Specified**
  by `baseline-read-only-guard` as the single named exception to "asks the server only to
  answer", with `test_refresh_is_emitted_by_exactly_one_request` as the tripwire so the exception
  list cannot grow quietly.
- The acordia ↔ aleph-mcp seam existing only as prose. **Declared** by
  `declare-acordia-spec-reference` as a `references:` entry in `openspec/config.yaml`, so
  `openspec doctor` reports it instead of `(none declared)`. Records-only by design — a reference
  indexes the referenced root's specs once its store is registered locally and runs no cross-root
  drift check (`dist/core/references.js`: "root resolution is never affected") — and the store is
  intentionally left unregistered so nothing is written into acordia. The tool-name expectation is
  therefore visible, not enforced; asserting it would invert the dependency.
- The client-method partition being declared and never verified — `test_every_client_method_is_classified`
  forced every public attribute onto one of two lists, but nothing checked that a method listed in
  `NOT_ENTITY_RETURNING` really returned no entities. **Closed** by T1-FIX-2's `NOT_SHAPING_CASES`,
  which feeds every such method a payload carrying an entity probe at that method's own copy-through
  depth, so listing a method there is no longer the cheap way to go green.
- The `build` job's licence assertion failing intermittently with `tar: stdout: write error` under
  `set -o pipefail`, because `grep -q` exits on the match while `tar` still has a chunk to flush.
  **Fixed** by PR #18 (`e394ed9`): both listings are captured into a variable and matched from a
  here-string, as the step already did for `meta`. Measured 0/30 false failures, from 19/30. The
  patterns were deliberately kept byte-identical, which is why note 5 above is still open.
- The shipped plugin `.mcp.json` running a shell at every server start, and the deliberate
  `aleph-mcp:keychain-miss` marker that keeps an omitted `env` entry from letting the server inherit
  an ambient `ALEPHCLIENT_API_KEY`. **Documented** in `plugins/aleph/README.md` (the setup section
  and "Why the Keychain entry is host-scoped"), which is where a plugin installer reads it. Never a
  defect — recorded here only until the README caught up.
- The metadata path failing permanently and degrading silently — a truthy non-dict `model` cached
  unchecked and then read with `.get` outside `_schemata`'s try, so `{"model": "https://..."}`
  raised `AttributeError` as a server defect and, being cached, kept doing so for the process
  lifetime; and only a success being memoised, so a broken `/api/2/metadata` was refetched by every
  entity-returning call. Both measured before the fix: two `get_entity` calls both raised
  `AttributeError: 'str' object has no attribute 'get'` with the route called once, and three calls
  against a 503 route cost twelve upstream requests. **Fixed and specified** by
  `harden-metadata-path`: a non-object `model` is refused by JSON type where it would have been
  cached — degrading the shaped tools through the existing arm, surfacing on the ontology tools
  where an empty answer would be a lie about the instance — the failure is negatively cached for a
  bounded 60s window on the shared clock, and a reply whose captions came from `_CAPTION_FALLBACK`
  *because the ontology could not be read* now says so, composing with the endpoint's own note. The
  three requirements are in `openspec/specs/mcp-tool-surface`. `_schemata`'s comment naming this as
  its own live counterexample is corrected in the same change.