## Context

`server.py`'s `_refusing` decorator is the single seam between this server's own judgement and
FastMCP's error surface. It exists because a refusal's message — "limit must be between 0 and
200" — is the part worth reading, and FastMCP wraps an untranslated exception in
`Error calling tool 'X': ...`, which reads as a server fault and which `mask_error_details`
deletes outright.

It selects on `ValueError`. Python raises `ValueError` for argument validation, for
`int("abc")`, for `json.loads(b"<html>")` and for `bytes.decode()` on non-UTF-8 — so selecting
on it means selecting on *a category of Python failure*, when what the seam wants is *a failure
this server chose to produce*. Those two sets overlap by accident, and the accident is load-bearing
in both directions today.

## Goals / Non-Goals

**Goals**

- One type that says "this server refused the call", raised only where that is true.
- A 2xx whose body is not JSON refused as the upstream fault it is, through the same error path
  every other upstream fault already takes.
- No change to any refusal message a caller reads today.

**Non-Goals**

- Retyping `config.py`'s validators. Those run inside pydantic at `Settings()` construction, before
  any tool exists; pydantic wraps them in `ValidationError` and the process fails to start. They
  are not on the seam and cannot reach it.
- Retyping `echo.py`'s policy-construction guards. Those fire at import time on a malformed
  `EchoPolicy` literal — a defect in this repo, which must not be dressed as a caller refusal.
  Leaving them bare `ValueError` is what makes that true after this change.
- Reclassifying anything `raise_for_status` already handles. A non-2xx is a status, and this change
  touches only the success path's decode.

## Decisions

### `Refusal` subclasses `ValueError`

The alternative — a fresh `Exception` subclass — is cleaner on paper and wrong here. `AlephClient`
is importable as a library and its refusals have always been `ValueError`; a caller with
`except ValueError` around a client call would silently stop catching them, which is the kind of
break that shows up as a crash in someone else's process rather than as a test failure in this one.
Subclassing keeps every such caller working while still letting the seam select precisely.

It lives in `errors.py`, next to `ResponseTooLarge`, which is the pattern it copies: a marker type
so a caller can catch by type instead of matching message text.

### The seam narrows, and that is the point

`except Refusal` instead of `except ValueError` means an in-body `int()` or `json.loads` now
reaches the caller as `Error calling tool 'X': invalid literal for int() ...` — prefixed, and
erased entirely under `mask_error_details`. That looks like a regression and is the intended
outcome: it is a defect in this server, and the prefix is how FastMCP says so. The failure mode it
replaces is worse, because a message that reads as a considered refusal tells the model the call
was wrong, and the model then spends turns rewriting arguments that were never the problem.

### A 2xx that is not JSON is refused, not retried

`raise_unparsable_body` is modelled on `raise_undecodable_body`, which already covers the adjacent
case — a body that contradicts its `Content-Encoding`. Three properties are copied deliberately:

- **It says the response arrived.** The status and headers were received, which is more than
  `raise_transport_failed` can claim, so the message says so and names the status. The status is
  the fact a reader wants first and it is already in hand.
- **It advises neither retry nor no-retry.** A maintenance page, an SSO interstitial and a proxy
  that answers `200` with its own HTML are transient on different clocks, and an instance serving
  a genuinely wrong content type is not transient at all. This server cannot tell them apart, and
  guessing would send the caller to hammer a dead instance or to give up on a live one.
- **It quotes the decoder through `_reported`.** `json.JSONDecodeError`'s message is a fixed
  string plus a position; `UnicodeDecodeError`'s adds the offending byte in hex. Neither echoes
  body content today — but the label costs nothing and the convention is what stops the next call
  site copying half the pattern.

The body itself is never quoted. It is unbounded attacker-influenced text, which is the whole
reason `_upstream_detail` drops any non-JSON error body rather than echoing it.

It is raised where the decode happens, inside `Transport.request`, so it carries the same
`context` and `resource` flags as every other refusal on that path and lands on the right error
class for a tool or a resource.

### The wrapper for a non-dict JSON body stays

`{"results": <body>}` for a bare array, string or number is unchanged. That branch reads a body
that *did* parse as JSON; this change only decides what happens when parsing fails. The claim that
the wrapper makes the resolver unable to tell an Aleph listing from any array is a separate parked
entry and stays parked.

### `client.py`'s two `ValueError` arms lose that type

Both were written to absorb an unguarded decode. `get_model`'s memo tuple
(`ResourceError, httpx.HTTPError, ValueError`) and `_schemata`'s degradation arm
(`httpx.HTTPError, ValueError`) exist so a non-JSON metadata body degrades captions instead of
hard-failing ten tools. After the guard, that body arrives as a `ResourceError` — `get_model` calls
the transport with `resource=True` — and both arms already catch `ResourceError` on a path that
degrades identically.

What would be left under `ValueError` is a defect in this module. Both arms carry a comment saying
they are named rather than bare precisely so that a module defect is not swallowed, and both are
pinned by a test that a bare `except Exception` breaks. Keeping `ValueError` after the guard would
contradict that comment on the one type most likely to be raised by a bug in argument handling.

The degradation behaviour itself is unchanged and is pinned by
`test_a_metadata_body_that_does_not_parse_degrades_rather_than_failing`, which parametrises the
four bodies this path cares about. That test passing untouched is the evidence that the arm swap
is behaviour-preserving.

## Risks / Trade-offs

- **A refusal site added later forgets the type.** Then it reaches the caller prefixed and masked,
  i.e. it fails loudly on the first test that calls it, rather than silently. A test asserts that
  no `raise ValueError(` survives in `client.py` or `scope.py` so the next site cannot copy the
  old spelling from its neighbours.
- **A third-party library inside a tool body raises `ValueError` for something the caller could
  act on.** Then a legible message becomes a prefixed one. There is no such library on these paths
  today — the only non-stdlib call inside a tool body is the transport, which raises `ToolError`
  and `ResourceError` and never escapes as `ValueError`.
- **A caller matching on the old decoder text.** `Expecting value: line 1 column 1 (char 0)` is not
  a string any reasonable caller matches on, and no test in this repo does.

## Migration Plan

Single change, no flag. The new refusal is strictly better-formed than the string it replaces, and
every other refusal keeps its text byte-for-byte.
