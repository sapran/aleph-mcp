# Implementation notes

Findings recorded during other work, kept out of the change that surfaced them. An entry leaves
this file when it becomes a spec requirement or is fixed — not when someone remembers to tidy up.

- **`httpx.ProxyError` reaches the model unsanitised, and its text is attacker-authored.**
  Found by security review of `fix/retry-connection-failures`; pre-existing, so parked rather
  than fixed there. `ProxyError` is a sibling of `ConnectError` under `TransportError`, not a
  subclass, so `transport._CONNECT_ERRORS` does not catch it and it never reaches
  `errors.py`'s sanitiser. httpcore builds its message from the proxy's `CONNECT` reason
  phrase (`httpcore/_async/http_proxy.py`), which h11 admits as `([ \t]|[^\x00\s])*` — every
  C0 control except NUL, `ESC` included — decoded with `errors="ignore"`. FastMCP then renders
  it verbatim, because `mask_error_details` defaults false. So a hostile or MITM'd forward
  proxy can write multi-kilobyte ASCII with ANSI escapes into a model-visible tool error,
  bypassing both the 200-char cap and the non-printable stripping of `echo.UPSTREAM_ERROR`. A
  forward proxy is a live deployment shape here, so this is worth a change of its own: catch
  `httpx.TransportError` at the top of `Transport.request` and route the non-retryable members through
  `raise_unreachable`. Do **not** simply add `ProxyError` to `_CONNECT_ERRORS` — a `CONNECT`
  that reached the proxy is not obviously undelivered, which is the argument that correctly
  keeps `ReadError` out.

- **A TLS verification failure is retried four times with the wrong advice.** Found by review
  of the same branch. httpcore maps `ssl.SSLError` from the handshake to `ConnectError`, so
  `CERTIFICATE_VERIFY_FAILED` — the misconfiguration the README anticipates for a self-signed
  instance with `ALEPH_MCP_VERIFY_TLS` left true — now costs three backoffs before failing,
  and the message speaks about network reachability. The real cause is visible only inside the
  quoted transport text. Retrying is harmless but pointless, since the failure is
  deterministic. Fixing it means classifying the cause (walk `e.__cause__` for an
  `ssl.SSLError`) and branching the message to name the setting, which is error classification
  rather than retry, so it was left out. A DNS failure also arrives as `ConnectError` and
  should keep being retried: a resolver hiccup is plausibly transient.

- **Only the connect path charges its elapsed time to the retry budget.** A slow 429/5xx round
  trip is still uncharged, so `max_retries` slow responses can exceed `timeout_secs` in total.
  That is pre-existing behaviour, not introduced by the connect retry, so the same one-line
  charge was not extended to the response path in that change. The connect path had to be
  charged because a connect can burn the whole connect phase without ever sleeping.

- **The shipped plugin `.mcp.json` runs a shell at every server start.** Both `env` values
  are `!`-prefixed commands: the host is `$ALEPHCLIENT_HOST`, and the key is read from the
  macOS login Keychain under a service name that includes the host. That behaviour is
  documented in `plugins/aleph/README.md` rather than only implied, because installing the
  plugin makes a Keychain read happen per session. A miss deliberately prints the marker
  `aleph-mcp:keychain-miss` instead of an empty string: the harness *omits* an `env` entry
  whose command prints only whitespace, and an omitted entry lets the server inherit an
  ambient `ALEPHCLIENT_API_KEY`. Non-macOS users are directed to declare their own server
  entry instead.

- **References to non-public siblings survive outside the README.** The open-source
  readiness branch removed the dead `../aleph-coldbackup` / `../datashare-mcp` links from
  `README.md`, but the same tool is still named in `src/aleph_mcp/server.py:50` (server
  instructions, so a model sees it), `src/aleph_mcp/config.py:19` (comment) and
  `plugins/aleph/skills/aleph-entity-graph/SKILL.md:62`. Parked because that branch was
  scoped to licensing, docs and CI with no `src/` changes, and `tests/test_tools.py`
  asserts on the instructions string. Decide before publication whether a public reader
  being pointed at a private tool is acceptable.

- **`openspec/config.yaml` declares a private remote.** The `acordia` reference points at
  `https://github.com/sapran/acordia-agents.git`, which is private; `acordia` is also
  named across the specs, the archived changes, `plugins/aleph/README.md` and this file.
  On publication `openspec doctor` or a register attempt hits a 404 on a repo the
  contributor cannot see. Parked: the declaration is deliberate and documented above, so
  removing it is a design decision, not a cleanup.

Retired since the last prune:

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

- `.github/workflows/ci.yml`, the `build` job's licence assertion: `tar tzf dist/*.tar.gz |
  grep -q '/LICENSE$'` runs under `set -o pipefail`, so it fails intermittently with `tar:
  stdout: write error` (exit 2). The sdist listing is 6373 bytes across 100 entries with
  `LICENSE` third from last, so `grep -q` exits on the match while `tar` may still have its
  final chunk to flush, and the EPIPE fails the pipeline. Observed twice on PR #12 while the
  same job re-run on `main @ 1952232` passed; PR #12 changes no path in the sdist, so the
  piped bytes are identical on both sides. It then went green on the same branch once the
  test commits changed the archive's size — timing, not content, decides it, which is what
  makes it a latent bug rather than a fixed one. Parked: outside T3's scope. One-line fix is to
  capture first, as the step already does for `meta` — `listing=$(tar tzf dist/*.tar.gz)`
  then `grep -q '/LICENSE$' <<<"$listing"`.
- `Transport.request` (`transport.py`, was `client.py:496`) decodes the body with an unguarded
  `jsonlib.loads`. `json.JSONDecodeError` and `UnicodeDecodeError` are both `ValueError`
  subclasses, so a 2xx whose body is not JSON — an HTML maintenance page, a proxy
  interstitial, a truncated body — reaches the model as a
  refusal reading `Expecting value: line 1 column 1 (char 0)`, indistinguishable from "you
  passed a bad id". The rational reply to a refusal is to change arguments and retry, against
  an upstream that is down. Run-verified identical on `main @ 1952232`, so the T3 seam
  relocates this and does not widen it; `errors.py:74` already guards the analogous connect
  case. The fix that also closes the note below: a dedicated `Refusal(ValueError)` raised at
  `client.py`'s own refusal sites, caught in place of bare `ValueError` — the pattern
  `errors.py:97` already sets for `ResponseTooLarge`. Parked: `client.py` is out of T3's
  scope; belongs with T2, which is already about error text.
- The T3 seam wraps the whole tool body, where the arms it replaced wrapped only the
  `await client.X(...)` call. Equivalent today — every body is one forwarding call — but a
  future in-body `int()`, `datetime.fromisoformat()` or nested `json.loads` would be
  relabelled as a client refusal with nothing to catch it. Same `Refusal` type fixes it.
  Parked: needs `client.py`.
- Resources have no counterpart to the fused `tool` helper: `@mcp.resource` is still reachable
  raw, and `schema_resource`'s translation is a hand-applied decorator nothing enforces. Two
  consequences, neither live today — a future *parameterised* resource would silently regress
  to FastMCP's `Error reading resource '<uri>': ` wrapping, and the decorator order is
  load-bearing but fails silently (`@_as_resource_error` above `@mcp.resource` imports,
  registers and serves the untranslated message). `collections_resource` and
  `schemata_resource` cannot raise `ValueError` at all, so decorating them now would be dead
  code. Fix is a ~4-line local `resource(uri, **kw)` factory mirroring `tool`. Parked: beyond
  T3's stated files and criteria.
- Comment drift naming the structure T3 deleted: `client.py:619` and
  `tests/test_collection_scope.py:334` and `:446` still say "each tool's `except ValueError`"
  or "no tool's `except ValueError` translates". The claims stay true of the single seam, but
  send a reader looking for per-tool arms that no longer exist. Parked: both files are outside
  T3's scope.
- `pyproject.toml` sets `line-length = 100` while `[tool.ruff.lint]` ignores `E501`, so line
  length is enforced only by `ruff format`, never by `ruff check`. Harmless today; noted
  because the contributor-facing constraint reads as if `ruff check` enforces it.

- **`test_search_derives_captions_from_the_instance_model` cannot fail.** Found while building
  the shaping seam (T1). Its mocked model declares the caption order `["name"]`, which is also
  the first entry of `_CAPTION_FALLBACK`, so the test passes whether or not the instance model
  reaches the slimmer -- it was the only integration test claiming to pin that plumbing. Left
  alone rather than rewritten: T1's `test_every_entity_returning_method_shapes_its_reply` now
  covers the same path with a discriminating model, so this one is superseded, not load-bearing.
  Deleting or strengthening it is a separate, purely-test change.

- **`get_entity_text` derives no caption.** `client.py` reads `entity.get("caption")` straight
  off the payload, where every slimmed path calls `derive_caption`. Live Aleph sends a null
  caption, so this is the one tool that can return `caption: null` for an entity the other tools
  would have captioned. Found during T1; fixing it changes a tool's output and so is a behaviour
  change, not a refactor.

- **A non-dict `model` from `/api/2/metadata` is a permanent hard failure.** `get_model` caches
  `payload.get("model") or {}` with no type check, and `_schemata` reads `model.get("schemata")`
  outside its own try, so a metadata body like `{"model": "https://..."}`, `{"model": [..]}`,
  `{"model": 3}` or `{"model": NaN}` (Python's json accepts bare NaN) raises `AttributeError`
  there. It reaches the caller as `Error calling tool '<name>': 'str' object has no attribute
  'get'` — prefixed, erased under masking — and because the bad value *is* cached it never
  refetches, so all ten shaped tools plus `list_schemata`, `get_schema` and the `aleph://schemata`
  resource stay broken for the process lifetime. Pre-existing and unchanged by T1-FIX-2, verified
  identical at `1e8e74c`; parked because fixing it is a behaviour change outside that brief. It is
  also the one live counterexample to the "an AttributeError here means a defect in this module"
  reading that `_schemata`'s comment states. One line in `get_model` closes it:
  `model = payload.get("model"); self._model = model if isinstance(model, dict) else {}`.

- **The marker guard covers every tool but only one of three resources.** `find_marker` runs inside
  `_refusing`, so `collections_resource` and `schemata_resource` — which are not decorated with
  `@_as_resource_error` — return without it. Inert today: both call unshaped client methods that
  build no markers. It becomes real only if a resource is ever pointed at a `@_shaped` method.

- **`find_marker` does not traverse tuples, sets or dict keys.** A marker in one of those positions
  is not found. No client method builds a tuple, a set or a non-string key into a reply, so nothing
  reaches those branches today, and the markers' own serialisation refusal still fires there — the
  outcome degrades to the pre-T1-FIX-2 message rather than leaking.

- **`_schemata()` does not cache its failures.** `get_model` memoises only a success, and
  `_schemata` swallows every exception, so a persistently broken `/api/2/metadata` costs the full
  retry budget on *every* entity-returning call while still returning `None`. Found during T1 and
  left alone: negative caching is a behaviour change. Note the test-suite side effect -- because
  respx raises on an unmocked route and that raise is swallowed, almost every test in the suite
  exercises the `schemata=None` path by accident. The sharper half: the degradation carries no
  signal at all. Every other degradation in `client.py` announces itself -- `search_entities` emits
  `TRUNCATED PAGE` / `EMPTY SLICE` / `EVERY COLLECTION` notes, `_slim_tags` attaches `_provenance`
  -- but a caption derived from the fallback order is indistinguishable from one the instance's own
  ontology produced. A `_note` when `schemata is None` would meet the standard the rest of the file
  already sets.

- **`get_profile` passes its `entities` field through unshaped.** It holds id strings in every
  fixture and on the live instance, so nothing leaks today, but the "binds every entity-shaped
  value in a response" requirement in `openspec/specs/mcp-tool-surface` would be violated by an
  instance that serialised objects there. Since T1 this fails closed rather than leaking: `_shape`
  refuses an unmarked entity-shaped dict. Read both halves of that trade -- on such an instance
  `get_profile` does not degrade, it stops answering entirely, and the refusal is not something
  the caller can act on. That is the right way round for unbounded document text reaching a model,
  but it is a real availability cost on a version bump rather than a free win. Deciding whether to
  mark the field is a spec question, not a refactor.

- **`_slim_entityset` copies upstream `entities` verbatim, and nothing fails closed there.**
  `get_entityset` and `list_entitysets` pass that field straight through, exactly as `get_profile`
  does -- but both sit outside T1's shaping seam, so the `_shape` guard never runs on their replies
  and the protection recorded in the note above does not extend to them. Found by review of the T1
  branch; parked because T1's scope is the ten entity-returning methods and netting these two means
  deciding whether an entityset's `entities` is entity-shaped at all, which is a spec question.

- **`_slim_tags` copies a tag row's non-string values through.** `entity_tags` and `profile_tags`
  truncate a row's *string* values and pass every other value on unchanged, so an entity object as a
  row's `value` arrives with all five blob properties intact. Aleph returns `{field, value, count}`
  rows there, so this needs the same upstream contract change as the notes above and leaks nothing
  today.

- **`_slim_collection(full=True)` copies `statistics` verbatim.** `get_collection` returns whatever
  that block holds, unread and unbounded; `list_collections` does not, because it slims with
  `full=False`. Same class as the three notes above: an aggregation slot that is copied rather than
  rebuilt.

  All four of these -- `get_profile.entities`, `_slim_entityset.entities`, a tag row's `value`, and
  `statistics` -- are one spec question about what counts as entity-shaped, not four refactors.
  Since T1-FIX-2 each is pinned by a `strict` xfail row in `NOT_SHAPING_CASES`, so the behaviour
  cannot change without the suite saying so, and fixing any of them forces this note to be closed.

- **`get_schema` echoes upstream schema names into a refusal, unbounded and un-neutralised.**
  `client.py:657` builds `f"Did you mean one of: {', '.join(close[:10])}?"` from the keys of
  `model["schemata"]`, which is upstream text from `/api/2/metadata` — no cap, no `!r`, and no
  `echo` policy, while `name!r` beside it is caller input and *is* escaped. Found by security
  review during T2 and reproduced against pristine `develop @ 01a48c4`, so it predates that
  change and is not introduced by it: a schema key carrying `ESC`, `NUL`, `U+202E` and a raw `"`
  arrives in the message with all four intact, and one 20,000-character key produced a
  20,104-character refusal. It reaches the model through `aleph://schema/{name}`, which
  `server.py`'s `_as_resource_error` seam forwards with `str(e)` — so unprefixed and surviving
  `mask_error_details`, the shape this repo reserves for caller-actionable refusals. Needs its
  own policy (a plain strip, since the names are interpolated without `!r`) plus a bound on the
  joined list rather than only on each name. Kept out of T2 because it is a behaviour change to
  a tool's output, not a move. Related and lower: `list_schemata` (`client.py:646`) returns
  `sorted(schemata)` — every upstream key, unbounded in count and length — into
  `aleph://schemata`, bounded only by `MAX_RESPONSE_BYTES` and carrying no `_provenance` label.

- **A policy built inline at a call site escapes both of `echo.py`'s guards.**
  `test_every_policy_has_a_cap_row` enumerates `vars(echo)`, so it sees only module-level
  policies declared in `echo.py`. `render(v, replace(PROPERTY_VALUE, max_chars=77))` at a call
  site is invisible to it and to every cap row, which defeats the "each site asks for the
  treatment by name" property the module exists to establish. Found by test review during T2.
  No such call site exists today — all seven name one of the four — so this is a missing
  enforcement, not a live defect. Closing it means either forbidding non-module policies at
  runtime or asserting the seven call sites against the four names.

- **`echo.COLLECTION_ECHO` leaves control characters to its call site's `!r`.** Found while
  building the policy module (T2); it is the behaviour the four helpers had, preserved deliberately
  rather than a new gap. `scope.check_collection_id` is the only caller and formats the result with
  `!r`, which escapes controls -- so the policy does not strip them itself. A second caller that
  interpolates the rendering plainly would put upstream control characters into a model-visible
  message. Recorded because the coupling is now between two files rather than inside one function.
  Closing it means either stripping in the policy (a behaviour change to the existing message, so
  its own change) or asserting the `!r` at the call site.

- **A non-list `results` from the collection listing escapes the `except ValueError` seam.**
  `scope.py:312-313` (was `client.py:879-880`, character-identical). The `isinstance(results[0],
  dict)` guard covers a body that arrives as a list or a scalar, because `Transport.request` wraps a
  non-dict body as `{"results": <body>}` -- but an Aleph *dict* body whose own `results` key is
  not a list reaches `results[0]` on a truthy non-list. Measured on both `develop` and the T5
  branch, byte-identical: `{"results": {"a": 1}}` raises `KeyError`, `{"results": 5}` and
  `{"results": true}` raise `TypeError`. `server.py` translates `ValueError` only, so these reach
  the model untranslated rather than as a legible refusal. Found by review during T5 and
  reproduced against pristine `develop`, so it predates that change. Fires only against an
  upstream or proxy answering 200 with an unexpected body shape.

- **"no collection with foreign_id X" absorbs an upstream malfunction.** `scope.py:321-325`,
  unchanged from `develop`. Any lookup payload without a usable `results[0]` -- including
  `{"status": "error"}` with no `results` key at all, and `{"results": [null]}` -- is reported to
  the model as an authorisation-or-existence problem naming `list_collections`. A proxy, an SSO
  interstitial or an unfamiliar Aleph version therefore produces a confident wrong diagnosis and a
  dead-end next step. Fail-closed, so no wrong rows are returned. Found by review during T5.

- **The `MAX_SCOPE_COLLECTIONS` boundary is unpinned.** Only `MAX + 1` is tested
  (`tests/test_scope.py`, `tests/test_collection_scope.py:371`); changing `>` to `>=` at
  `scope.py:161` -- which would refuse a legitimate ten-collection scope -- passes the whole
  suite. Pre-existing gap inherited from `test_collection_scope.py`, not introduced by T5. Related
  and also unpinned: the dedup runs *before* the bound, so eleven spellings collapsing to ten are
  accepted. Closing it is one row in the existing parametrised table.

- **A single-element `["*"]` is refused with the wrong reason.** `scope.py:150` fires the mixed-
  scope message -- "cannot be combined with named collections" -- for a list that names no other
  collection. Unchanged from `develop`, untested anywhere. Correcting it changes a refusal
  message, so it is a behaviour change rather than a move.

- **`openspec/config.yaml`'s layout paragraph is three modules stale.** It lists `server.py`,
  `client.py`, `readonly.py`, `config.py` and `errors.py` and names none of `echo.py` (T2),
  `scope.py` (T5) or `transport.py` (T4). Documentation only -- no spec assertion depends on it --
  so it is parked rather than corrected inside a behaviour-preserving refactor. One paragraph to
  fix, and cheapest to do once rather than once per task.
