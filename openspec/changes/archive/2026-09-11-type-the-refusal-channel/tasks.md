## 1. Reproduce, red first

- [x] 1.1 Assert a `200` carrying an HTML maintenance page is refused with a message naming the call context and the status, not with a bare `Expecting value: line 1 column 1 (char 0)`.
- [x] 1.2 Assert the same for a `200` whose body is not valid UTF-8 at all (a PNG), which arrives as `UnicodeDecodeError` rather than `JSONDecodeError`.
- [x] 1.3 Assert the same on the resource path (`aleph://schema/{name}`), so the refusal lands on `ResourceError` rather than `ToolError`.
- [x] 1.4 Assert the refusal quotes no part of the body, and that the decoder text it does quote is labelled untrusted.
- [x] 1.5 Assert a tool body raising a `ValueError` of its own is *not* translated by the seam — it reaches the caller as a server fault, not as a refusal.
- [x] 1.6 Assert every refusal `AlephClient` makes itself is an instance of the new type, and still an instance of `ValueError`.
- [x] 1.7 Run the new tests and record that each fails with the symptom the implementation-notes entry names.

## 2. Add the refusal type

- [x] 2.1 Add `Refusal(ValueError)` to `errors.py` with a docstring stating what it means and why it subclasses `ValueError` rather than `Exception`.
- [x] 2.2 Retype all 15 `raise ValueError(` sites in `client.py`. No message text changes.
- [x] 2.3 Retype all 10 raise/return sites in `scope.py`, including the `_no_such_collection` and `_unusable_listing` factories. No message text changes.
- [x] 2.4 Leave `config.py` and `echo.py` bare: those fire before any tool exists, or on a defect in this repo, and must not read as caller refusals.
- [x] 2.5 Add a test that no `raise ValueError(` survives in `client.py` or `scope.py`, so the next refusal site cannot copy the old spelling from its neighbours.

## 3. Narrow the seam

- [x] 3.1 Change `_refusing`'s `except ValueError` to `except Refusal`, and rewrite the docstring paragraph that says "the client raises ValueError for every refusal it makes itself".
- [x] 3.2 State in that docstring why narrowing is the point: a defect reaching the caller prefixed is better than a defect reading as a considered refusal.

## 4. Guard the body decode

- [x] 4.1 Add `raise_unparsable_body(exc, *, context, status, resource)` to `errors.py`, modelled on `raise_undecodable_body`: names the status, says the response arrived, advises neither retry nor no-retry, quotes the decoder through `_reported`, quotes no part of the body.
- [x] 4.2 Wrap `Transport.request`'s final `jsonlib.loads(body)` and route `ValueError` to it, carrying the call's own `context` and `resource`.
- [x] 4.3 Leave the `{"results": <body>}` wrapper for a non-dict *parsed* body untouched.

## 5. Narrow `client.py`'s two absorbing arms

- [x] 5.1 Drop `ValueError` from `get_model`'s memo tuple, leaving `ResourceError` and `httpx.HTTPError`.
- [x] 5.2 Drop `ValueError` from `_schemata`'s degradation arm and rewrite the long comment that exists only to explain why `ValueError` was there.
- [x] 5.3 Confirm `test_a_metadata_body_that_does_not_parse_degrades_rather_than_failing` passes unchanged for all four bodies — that is the evidence the swap is behaviour-preserving.
- [x] 5.4 Extend the module-defect test to cover a `ValueError` raised inside `get_model`, which must now reach the caller rather than degrade.

## 6. Verify

- [x] 6.1 Full suite green; `ruff check`, `ruff format --check`, `mypy` clean.
- [x] 6.2 Mutation-test every new assertion: reintroduce each defect, watch the new test go red with the reported symptom, restore. 22 mutations, all killed; the first pass left two survivors — a hardcoded `200` at the call site (closed by a `204` test) and one mutation of mine that was a no-op (rewritten).
- [x] 6.3 Re-run the end-to-end measurement from the implementation-notes entry through the shipped MCP path and record the new messages.
- [x] 6.4 Confirm no existing refusal message changed: the suite's message assertions are the check.

## 7. Sync and close

- [x] 7.1 `openspec validate --strict`.
- [x] 7.2 Sync the delta into `openspec/specs/mcp-tool-surface/spec.md` and archive the change.
- [x] 7.3 Close entry 1 in `docs/implementation-notes.md`, renumber the work plan, and park anything this change surfaced without fixing.
