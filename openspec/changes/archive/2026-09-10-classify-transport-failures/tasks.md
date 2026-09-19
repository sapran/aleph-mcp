## 1. Add the two new refusals to `errors.py`

- [x] 1.1 Add `raise_tls_untrusted(exc, *, context, resource=False)`: names `ALEPH_MCP_VERIFY_TLS`,
      states the failure is deterministic, gives both readings (self-signed instance, intercepted
      connection) and recommends neither, and sanitises/labels the transport text as
      `raise_unreachable` does.
- [x] 1.2 Add `raise_transport_failed(exc, *, context, resource=False)`: says the request may have
      been received, never that no response was received, keeps the read-only-so-nothing-changed
      clause, and sanitises/labels the transport text identically.
- [x] 1.3 Factor the shared `render(str(exc), UPSTREAM_ERROR)` + empty-message handling used by all
      three raisers, so a future call site cannot copy half of the pattern.

## 2. Classify at the one seam in `transport.py`

- [x] 2.1 Add a bounded `__cause__`/`__context__` walk for `ssl.SSLError`, with a visited set
      against cyclic chains.
- [x] 2.2 Widen the loop's `except _CONNECT_ERRORS` to `httpx.TransportError` and dispatch: TLS
      cause → `raise_tls_untrusted`; `ProxyError` → `raise_unreachable` without retrying;
      `ConnectError`/`ConnectTimeout` → retried as today, then `raise_unreachable`; everything
      else → `raise_transport_failed`.
- [x] 2.3 Keep the budget charged for a failed attempt whichever bucket it lands in.

## 3. Guard tests

- [x] 3.1 Enumerate `httpx.TransportError`'s subclasses transitively from the live module and
      assert each one reaches a tool error naming the call context — the partition verified, not
      declared.
- [x] 3.2 Assert the hostile proxy phrase is capped, stripped of control bytes and labelled
      untrusted. The 4102-character measurement was taken through `fastmcp.Client`, but the
      landed test asserts at the `Transport` seam: the MCP boundary only prepends
      `Error calling tool 'X': ` and the cap under test is applied below it, so the assertion
      and the evidence differ by that fixed prefix. Recorded rather than restated, because the
      docstring cites the boundary figure.
- [x] 3.3 Assert a read-side failure does not claim that no response was received.
- [x] 3.4 Assert a TLS-caused connect makes exactly one attempt and names the setting, and that a
      connect with no TLS cause is still retried to the budget.
- [x] 3.5 Mutation-prove each new test, with a green control between every mutation.

## 4. Land

- [x] 4.1 Run ruff, mypy, the full suite and `openspec validate --strict`.
- [x] 4.2 Sync the delta into the published spec and archive the change.
- [x] 4.3 Close work-plan item 1 in `docs/implementation-notes.md`, renumber the plan, the section
      headings and every in-prose cross-reference.
- [x] 4.4 Delete `tests/test_zz_repro.py`.
