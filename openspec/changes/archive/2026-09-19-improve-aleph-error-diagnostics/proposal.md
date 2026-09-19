## Why

A consumer of this server audited a week of real analyst traffic against it and filed a
field report. Two of its findings are this server's to fix, and both are about what a
failure *tells* the caller rather than about which calls fail.

- **A retryable status says nothing about its own retrying.** 33 calls failed with HTTP
  503 (24 `get_entity`, 8 `search_entities`, 1 `get_collection`). All of them fell through
  `raise_for_status` to the generic final line, which reports the status and the upstream
  body and nothing else. The server knows four facts at that moment that it does not
  surface: that the status is in `_RETRY_STATUS`, how many attempts it made, whether the
  response carried `Retry-After`, and its value. Without them a caller cannot tell a
  refusal that spent its retry budget from one that never retried — the `budget_spent`
  clause covers only the narrower case where the wall clock, not the count, ended the
  loop. The reporter retried at deliberate 60-150 s spacing, so this is not a retry-storm
  fix; it is what stands between an honest coverage statement and a silently incomplete
  sweep.

- **Identifier validation is correct and unhelpful.** 9 calls passed a rendered property
  label where an identifier belongs (`'Email 1.2'`, `'Pages 1.1'`). `_check_entity_id`
  refuses them with one message naming only the charset. The refusal is right and must
  stay strict; the message never says where a real identifier comes from. An independent
  audit of a different corpus found the same class, so two measurements agree on it.

## What Changes

- **Retryable failures report their retry facts.** For a status in `_RETRY_STATUS`, the
  error states that the status is retryable, how many attempts were made, and what the
  **final** response advertised as a next wait. A parsed wait is reported normalised —
  through this server's one parser and bounded by the retry sleep ceiling — and framed as
  what the response advertised rather than as the wait this call would have taken, since
  the transport also clamps by the remaining budget. The raw header text is never echoed; an unparseable
  header is reported distinctly from an absent one; and an absent one is reported as *the
  final response advertised no next wait*, since an earlier attempt may have advertised one
  that was honoured.
- **Identifier refusals name the source of a real identifier.** Each of the three fields
  validated by `_check_entity_id` — `entity_id`, `profile_id`, `entityset_id` — gains a
  constant clause naming the reply field an identifier is read from. The charset and the
  refusal behaviour do not change.

## Explicitly not in scope

- **No semantic retryability classification.** The report asked for "retryable vs not, and
  a suggested wait". This change refuses the second half and narrows the first. The
  observed 503 bodies carry Elasticsearch's `state not recovered / initialized`, and
  classifying on that text would make a caller's retry decision depend on upstream prose
  that is not a contract and can change silently. Absent `Retry-After` the server cannot
  honestly distinguish initialization from overload, so any suggested wait would be
  invented. The facts are exposed; the judgement stays with the caller.
- **Not machine-readable: the error path this server raises through serialises text only.**
  A `ToolError` is delivered as an error flag plus text content. MCP's result type *can*
  carry structured content alongside that flag, and a raw client can read it, so a
  structured error field is possible — it is simply not what this server emits today, and
  adding one would be a deliberate extension of the published result contract. This change
  improves error *text*, and is therefore a partial answer to the report's ask.
- **No heuristic classifier on the refused value.** The hint is a per-field constant, not
  an inference from the shape of what was passed. A "looks like a label" test would add a
  second classifier that misses other rendered labels and changes nothing about validation.
- **The MCP transport faults are not ours.** 17 failures read `transport: stdio  stage:
  receive  failure: timeout`. That text is emitted by the MCP host when no tool response
  arrives; this server is not its author and cannot annotate a reply it never sent.
  Correlating it needs host logs plus this server's process lifecycle timestamps, not a
  code change here.
- **`get_entity_text` returning zero characters is unresolved.** The reporter correctly
  declined to file it as a defect. Documenting which types yield extractable text requires
  establishing the upstream contract first, which this change does not do.
- **The stale versioned plugin path is not ours.** Nothing in the shipped prose or
  references pins a plugin version; the reporter reached that conclusion independently and
  an audit of a second corpus agrees.

## Capabilities

### Modified Capabilities

- `mcp-tool-surface`: the error surface is a published contract, and both changes alter
  what a failure states.
