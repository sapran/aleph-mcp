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
