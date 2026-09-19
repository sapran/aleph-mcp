## Context

See `proposal.md` for why. Two error messages change; no call succeeds or fails differently.

The relevant code:

- `src/aleph_mcp/errors.py:34` `raise_for_status` — takes `attempts` and `budget_spent`
  already, branches per status, and ends at line 89 with a generic
  `f"{context}: unexpected HTTP {resp.status_code}.{detail}{budget}"`. A `503` reaches that
  line. `_budget_clause` at line 13 is appended only when `budget_spent` is true.
- `src/aleph_mcp/transport.py:89` `_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})`.
  `_retry_delay` at line 137 reads `Retry-After`, but **is not called for the response that
  reaches `raise_for_status`**: line 251 is
  `delay = 0.0 if give_up else min(_retry_delay(resp, attempt), budget)`, so it is skipped
  exactly on the terminal `give_up` path. It also returns a plain `float`, falling back to
  `_backoff_delay` when the header is absent or unparseable, so its return value cannot
  distinguish the three cases this change must report.
- `src/aleph_mcp/client.py:105` `_check_entity_id`, raising `Refusal` at line 107. Called
  for three fields: `entity_id` (6 sites), `profile_id` (4), `entityset_id` (2).

## Goals / Non-Goals

**Goals**

- A retryable refusal states retryability, attempt count, and the advertised wait or its
  absence.
- An identifier refusal names where a real identifier comes from, per field.

**Non-Goals**

- No structured error envelope. One is possible — MCP's result type can carry structured
  content alongside the error flag — but this server's error path emits text today, and
  adding a structured field is a deliberate change to the published result contract, not
  part of this one.
- No classification from upstream body text.
- No change to which statuses are retried, to the retry budget, to the charset, or to any
  refusal decision.
- No change to `get_entity_text` documentation; the upstream contract is not established.
- Nothing about the MCP host↔server stdio stage, which this server does not author.

## Decisions

**A shared parser, because the value is not already computed.** Extract the header read
from `_retry_delay` into one function returning a **tagged result with three states** —
`absent`, `invalid`, and `seconds(float)` — because the message must distinguish all three
and `float | None` has no representation for the middle one. A frozen dataclass carrying a
`Literal["absent", "invalid", "seconds"]` tag plus an optional value is sufficient; the
`seconds` value is bounded by `MAX_RETRY_SLEEP_SECS`. `_retry_delay` calls it and falls back
to `_backoff_delay` as it does today; the terminal path calls it on the final response,
which nothing does now. One parser is what makes the reported value provably the
normalisation the transport applies to the same header, and it is why this cannot be done by
reading the header a second time in `errors.py`.

**Advertised-and-normalised, not honoured.** `transport.py:251` is
`min(_retry_delay(resp, attempt), budget)`, so the wait actually taken is clamped by the
call's remaining wall-clock budget as well as by the ceiling. A message calling the reported
number an honoured wait would therefore be false whenever the budget was the binding
constraint — and on the terminal path the budget is often exhausted, so that is the common
case, not the corner. Passing the remaining budget into the message was considered and
rejected: it reports what this one call would have done rather than what the response asked
for, which is the fact a caller deciding whether to re-ask actually needs, and it couples
the error text to a value that is meaningless once the call has ended.

**Where the retry facts are composed.** In `errors.py`, from values passed in:
`attempts`, whether the status is retryable, and the parser's result for the final
response. This keeps `errors.py` free of retry policy and leaves `_RETRY_STATUS` one owner.

Alternative considered: have `errors.py` read the header itself. Rejected — two readers of
one untrusted header is how the value reported in the message and the value the transport
normalises drift apart.

**Why the claim is scoped to the final response.** Attempts are retried with their own
waits, and only the last response reaches the refusal. A message saying "no wait was
advertised" would be false whenever an earlier attempt advertised one that was honoured.
Reporting the final response's advertisement is true without tracking a per-attempt delay
history, which nothing else needs.

**Why the retryability claim comes from the status and not the body.** A caller that reads
"not retryable" from Elasticsearch's `state not recovered / initialized` would be trusting
a string no contract governs. The same body appears whether the index is initialising or
the cluster is degraded, and the status is the only signal with a defined meaning. Stating
the status's retryability and the absence of an advertised wait is strictly weaker than
what the report asked for, and it is what this server can defend.

**Why the identifier clause is a per-field constant.** The three fields have different
legitimate sources, so one shared sentence would be wrong for two of them. A constant per
field is honest, needs no inspection of the rejected value, and cannot misfire on a label
shape it was not written for.

**Why the message and not a new field.** The error path this server raises through
serialises text only. MCP's result type can carry structured content alongside the error
flag, and a raw client can read it, so a structured error field is possible rather than
impossible — it would be a deliberate extension of the published result contract, and is
out of scope here.

## Risks / Trade-offs

- **The report asked for machine-readable classification and gets text.** -> Recorded in
  the proposal and the spec as a partial answer, with the transport reason. The caller can
  still act on it: "retryable, N attempts, no advertised wait" is sufficient to decide
  between re-asking and reporting a gap.
- **Longer error text on the retry path.** -> Bounded: three facts, appended only for a
  retryable status, and the generic branch is already the longest message on the surface.
- **Two messages are asserted in tests by substring.** -> Error wording *is* the published
  contract here, so these assertions are behaviour, not incidental text. Each is updated to
  the new contract; one is deleted only where the delta makes what it asserts obsolete. New
  exact assertions cover the retry facts and the per-field source clauses.
