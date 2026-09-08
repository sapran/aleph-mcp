# Implementation notes

Findings recorded during other work, kept out of the change that surfaced them. An entry leaves
this file when it becomes a spec requirement or is fixed — not when someone remembers to tidy up.

- **`httpx.ProxyError` reaches the model unsanitised, and its text is attacker-authored.**
  Found by security review of `fix/retry-connection-failures`; pre-existing, so parked rather
  than fixed there. `ProxyError` is a sibling of `ConnectError` under `TransportError`, not a
  subclass, so `AlephClient._CONNECT_ERRORS` does not catch it and it never reaches
  `errors.py`'s sanitiser. httpcore builds its message from the proxy's `CONNECT` reason
  phrase (`httpcore/_async/http_proxy.py`), which h11 admits as `([ \t]|[^\x00\s])*` — every
  C0 control except NUL, `ESC` included — decoded with `errors="ignore"`. FastMCP then renders
  it verbatim, because `mask_error_details` defaults false. So a hostile or MITM'd forward
  proxy can write multi-kilobyte ASCII with ANSI escapes into a model-visible tool error,
  bypassing both the 200-char cap and the non-printable stripping in `_as_quoted_data`. A
  forward proxy is a live deployment shape here, so this is worth a change of its own: catch
  `httpx.TransportError` at the top of `_request` and route the non-retryable members through
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
- `client.py:496` decodes the body with an unguarded `jsonlib.loads`. `json.JSONDecodeError`
  and `UnicodeDecodeError` are both `ValueError` subclasses, so a 2xx whose body is not JSON
  — an HTML maintenance page, a proxy interstitial, a truncated body — reaches the model as a
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

- **`_slim_tags` copies each aggregation row through, so a row that is an entity survives it.**
  `entity_tags` and `profile_tags` truncate a row's string values and pass every other value on
  unchanged, so an entity object in the `results` list arrives with its properties intact. Aleph
  returns `{field, value, count}` rows there, so this needs the same upstream contract change as the
  two notes above and leaks nothing today. Recorded from the T1-FIX work, where the new
  `NOT_SHAPING_CASES` row for these two methods probes the position beside the aggregation rather
  than inside it; parked with its two siblings because netting all three is one spec question about
  what counts as entity-shaped, not three refactors.
