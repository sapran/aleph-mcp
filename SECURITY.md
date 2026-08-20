# Security policy

## Reporting a vulnerability

Report privately through GitHub: **[Security → Report a vulnerability][report]**. That
opens a private advisory visible only to the maintainer.

Please do not open a public issue for a security problem, and please do not include a
real Aleph API key or any excerpt of a real collection's content in the report. A
description of the request and the response shape is enough; if a proof of concept needs
data, use a local instance with synthetic entities.

This is a single-maintainer project. Reports are acknowledged as soon as they are seen,
and you will be told whether a fix is in progress rather than left waiting silently.

[report]: https://github.com/sapran/aleph-mcp/security/advisories/new

## Supported versions

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| 0.1.5 | No — 0.1.6 closed further security findings |
| Below 0.1.5 | **No — known credential defects, do not use** |

There is no backport branch: a fix lands in a new release, so "supported" means the
latest one. Use it.

Every install path in this project pins a full commit SHA, which means an old, vulnerable
tree stays installable forever. Two credential-handling defects were fixed before this
repository was public, and both are the subject of published advisories:

- **Before 0.1.4**, the Aleph API key could reach stderr. `Settings` rendered the
  assembled settings dictionary as the `input_value` of an unrelated missing-field error,
  so a key exported without a matching host alias was written into whatever log the MCP
  host captured.
- **Before 0.1.5**, the credential was not bound to its destination. The plugin manifest
  read the key from the macOS Keychain unconditionally while the host came from the
  ambient environment, so a `.env` arriving inside a cloned repository could point the
  client at an attacker-chosen origin with your real key attached.

If you pinned a SHA at or before either point, move to the current release and re-store
your Keychain entry under the host-scoped name.

## What this project treats as a security boundary

Worth stating plainly, because the boundary is not where it usually is. Tool-level
permission in an agent harness is not relied upon here. Two things are:

1. **The credential.** Use an Aleph role whose collection ACL is `read=true,
   write=false`. Then Aleph refuses destructive endpoints server-side regardless of what
   any agent, tool or prompt asks for.
2. **The outgoing-request allowlist** in `src/aleph_mcp/readonly.py`. Every request this
   server issues — redirect hops included — is matched against a fixed tuple of
   `(method, path)` pairs and its origin is pinned to the configured host, before the
   request is sent. Widening that tuple is the only way to widen the surface.

The project also assumes **documents indexed in an Aleph collection are attacker
plantable**. Extracted text is third-party content, so it is returned inside a
per-response nonce fence and labelled as data rather than instruction.

## In scope

- Any request reaching an endpoint outside the `readonly.py` allowlist, or any origin
  other than the configured one — via a tool argument, a redirect, a base-path prefix, a
  URL-encoding difference, or configuration.
- The API key appearing in any output: an error message, a log line, a tool result, an
  exception rendering, or a refusal message.
- Document text or upstream error text escaping the nonce fence in `client.py`, or
  otherwise reaching the model in a form that presents as server-authored instruction
  rather than as quoted data.
- A response able to exhaust memory despite the streamed size ceiling.
- The plugin credential lookup in `plugins/aleph/.mcp.json` yielding a key for a host it
  was not minted for, or falling back to an ambient `ALEPHCLIENT_API_KEY`.

## Out of scope

- `POST /api/2/match` being a non-GET request. It is deliberate and allowlisted: it is a
  read that takes a JSON body. Aleph exposes no GET equivalent.
- Anything that requires a write-scoped API key. The documentation tells operators to use
  a read-only role; a finding that depends on ignoring that is a finding about your
  Aleph's ACL, not about this server.
- Vulnerabilities in Aleph itself — report those to
  [alephdata/aleph](https://github.com/alephdata/aleph). Findings in how *this* server
  calls Aleph are in scope.
- The server trusting the operator's own environment. `ALEPHCLIENT_HOST` and
  `ALEPHCLIENT_API_KEY` are configuration; anyone who can set them can already run
  arbitrary code as you.
