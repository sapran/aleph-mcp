## Why

`server.py`'s refusal seam translates `ValueError`. That is the wrong seam in both directions,
and the two halves have the same cause: the type says *where a failure came from* nowhere, so the
seam has to guess from a class that Python hands out for a dozen unrelated reasons.

Measured on `develop @ 7f9c139`, through the shipped MCP path:

- **Too wide.** `Transport.request` ends at an unguarded `jsonlib.loads(body)`. Both
  `json.JSONDecodeError` and `UnicodeDecodeError` are `ValueError` subclasses, so a **2xx whose
  body is not JSON** reaches the model dressed as a caller refusal. An HTML maintenance page on a
  `200` produced `Expecting value: line 1 column 1 (char 0)`; a `200` carrying a PNG produced
  `'utf-8' codec can't decode byte 0x89 in position 0: invalid start byte`. Both arrive unprefixed
  and survive `mask_error_details`, which is the exact shape this repo reserves for a deliberate,
  caller-actionable refusal — so the rational reply is to change arguments and retry, against an
  instance that is down. Neither message names the call context, the status, or the fact that
  anything upstream went wrong.
- **Too narrow.** The seam wraps the whole tool body, where the arms it replaced wrapped only the
  `await client.X(...)` call. Measured with a tool body calling `int()` on upstream text: the
  caller received `invalid literal for int() with base 10: 'not-a-number'` — a Python defect
  relabelled as this server's considered refusal, with nothing anywhere to catch it. Every body is
  one forwarding call today, so this is latent rather than live; a single in-body `int()`,
  `datetime.fromisoformat()` or nested `json.loads` makes it live.

The same untyped channel is why `client.py` carries two `except ... ValueError` arms whose
comments have to explain, at length, that `ValueError` there means *upstream sent a body that is
not JSON* rather than *this module has a bug* — a distinction the type could have made.

## What Changes

- A dedicated `Refusal(ValueError)` is added to `errors.py` and raised at every site where this
  server refuses a call on its own judgement — argument validation in `client.py`, scope
  resolution in `scope.py`. It subclasses `ValueError` so that a library caller catching
  `ValueError` today keeps working.
- `server.py`'s seam SHALL translate `Refusal` and nothing wider. A `ValueError` raised for any
  other reason inside a tool or resource body reaches the caller as the server fault it is,
  instead of being relabelled as a considered refusal.
- `Transport.request`'s final decode is guarded. A 2xx whose body is not JSON — undecodable bytes
  or well-formed bytes that are not JSON — SHALL be refused as an upstream fault through this
  server's own error path, naming the call context and the status that arrived, with the decoder's
  own text sanitised and labelled untrusted by the policy that governs every other quoted upstream
  string.
- The two `except ... ValueError` arms in `client.py` (`get_model`'s memo, `_schemata`'s
  degradation) drop `ValueError` from their tuples. The upstream fault they were absorbing now
  arrives as a `ResourceError`, which both already catch; what is left under `ValueError` there is
  a defect in this module, which those arms exist not to swallow.

## Capabilities

### New Capabilities

None. Both halves sharpen requirements `mcp-tool-surface` already makes — one about which
failures surface as caller refusals, one about which failures are refused through this server's
own error path.

### Modified Capabilities

- `mcp-tool-surface`: *Invalid arguments surface as tool and resource errors* gains the
  contract that a refusal is a distinct type, and that a failure which is not one SHALL NOT be
  presented as one. *Every transport failure is refused through this server's own error path*
  gains the successful-but-unparsable body, which is the one remaining response failure that
  left this server as itself.

## Impact

- `src/aleph_mcp/errors.py` — new `Refusal` type and `raise_unparsable_body`.
- `src/aleph_mcp/client.py` — 15 refusal sites retyped; two `except` tuples narrowed.
- `src/aleph_mcp/scope.py` — 10 refusal sites retyped; gains an `errors` import.
- `src/aleph_mcp/transport.py` — the final decode guarded.
- `src/aleph_mcp/server.py` — the seam catches `Refusal`.
- No tool signature changes, no new dependency, no configuration.
- **Message change, not signature change**: a 2xx non-JSON body, which used to produce a bare
  decoder string, now produces a refusal naming the context and the upstream fault. No existing
  refusal text changes.
