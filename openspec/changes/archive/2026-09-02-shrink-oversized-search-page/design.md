## Context

See `proposal.md` — Why. Two properties of the existing code shape the design:

- `_read_bounded` refuses **while the body streams**, at the moment the running total crosses
  `MAX_RESPONSE_BYTES`. So the size it reports is a *lower bound* on the true body, never the
  whole of it — everything after the crossing chunk was never read.
- `raise_too_large` is reachable from every tool and both resources. Only `search_entities`
  has a page size to reduce, so the recovery cannot live in the raiser or in `_request`.

## Goals / Non-Goals

Goals: a usable partial page instead of a discarded one; a caller that can resume; a bounded
number of extra requests.

Non-Goals:

- **Not** a binary search for the largest page that fits. Each probe is a whole request against
  Aleph and buffers up to 25 MiB again.
- **Not** a relaxation of the ceiling. The allocation bound is unchanged.
- **Not** applied to any other tool. `get_entity_text` already slices; `expand_entity` is
  capped at 200; a facet aggregation has no row count to lower.

## Decisions

**Catch by type, not by message.** `raise_too_large` gains `TooLargeToolError` /
`TooLargeResourceError`, mixing a `ResponseTooLarge` marker into the existing `ToolError` /
`ResourceError`. The alternative — matching the message text — couples the loop to prose that
exists for a model to read, and would break silently the first time the wording improves.
Message text is deliberately unchanged so the existing tests that match on it still pass. The
marker carries no data: see the next decision.

**Halve from the first shrink; a proportional aim was tried and rejected.** The attractive
design is to aim proportionally, since the crossing size rides on the exception and a body
barely over ought to need a page barely smaller. It does not work, and review caught it: the
refusal happens *at the chunk that crosses*, so the reported size is always within a fraction
of a percent of the ceiling however large the real body is. Measured — a body ten times over
the ceiling reported `1.0025x`, making `page * 0.8 * limit / size` a fixed `0.798 * page`. The
schedule was therefore `0.8/0.4/0.2`, rescuing bodies only up to 5x over; halving gives
`0.5/0.25/0.125` and rescues 8x for the same number of requests. So the proportional branch
cost accuracy and bought nothing, and `size`/`limit` on the exception went with it — which
also removed the local `raise_too_large` needed to attach them, and with it a reference cycle.
A real proportional aim needs a real body size (`Content-Length`, absent `Content-Encoding`)
and is a separate change.

**Halving does not bound the facet-dominated case.** The body is roughly the facet block plus
the page times the row size, and lowering `limit` shrinks only the second term. A search whose
size comes from its facets spends every hop and still fails, at any schedule. The deadline
below is what bounds that, so the two are not alternatives.

**One deadline across the whole shrink loop.** `_request` bounds each request on its own
budget, but a shrink issues a fresh one, so without a deadline four hops multiply that budget
by `MAX_SEARCH_SHRINKS + 1` — the same amplification the per-request budget exists to prevent,
one level up. Reviewed worst case at the shipped defaults was ~1360s and 16 requests for one
tool call. `_monotonic` is the already-indirected clock, so this is testable on a fake one.

**`max(1, min(page // 2, page - 1))`.** The `min` guarantees strict decrease and the `max`
keeps it above the floor. With halving the `min` is provably redundant, since
`page // 2 <= page - 1` for every `page >= 2` — the helper's precondition. It stays as
belt-and-braces against a future change to the aim, and the sweep test pins the invariant
rather than the clamp.

**Withhold both markers when the reduced page served no rows.** `offset + 0` is the offset
just used, so a caller obeying `continue_from_offset` repeats the identical request and pays
the whole reduction again. An absent key is the honest signal, and the `_note` says the query
itself has to change.

**Release both buffers at the refusal.** The exception's traceback keeps `_read_bounded`'s
frame alive, so the accumulated body and the crossing chunk are retained with it, once per
hop. Measured: 106 MiB of resident growth against a 25 MiB ceiling before the fix, 4.16x. The
crossing chunk matters as much as the list — for a gzip body the ceiling is crossed on the
first decoded chunk, so the list is empty and the chunk is the whole body, and httpx decodes
with no `max_length`.

**A page of one, and `limit=0`, re-raise.** Below one row there is nothing left to shrink, and
a facet-only search is oversized for a reason no page size fixes. Both raise the ceiling error,
which already tells the caller to narrow.

**Notes compose rather than overwrite.** A shrunk page whose total exceeds 9999 is both
truncated and unenumerated. Joining a list of notes is why `test_search_notes_unreachable_tail`
keeps passing while the new statement is added.

**`limit` and `offset` report what was served, not Aleph's echo.** Aleph echoes the `limit` it
was asked for. Reporting that would contradict `continue_from_offset` on the same response, so
both are overwritten with the served values to keep the three consistent.

## Risks / Trade-offs

- **Up to `MAX_SEARCH_SHRINKS` extra requests and repeated ~25 MiB buffering on one call.** →
  Bounded at 3, and only reachable on a page that would otherwise have failed outright. Peak
  allocation is measured rather than assumed: 29.7 MiB of resident growth for four refusals
  against a 25 MiB ceiling, 1.16x, once both buffers are released at the refusal. Before that
  release it was 106 MiB, 4.16x, so this was a real regression and not a theoretical one.
- **Wall clock per tool call.** → Bounded by one deadline across the loop rather than by the
  hop count, because a facet-dominated body spends every hop regardless.
- **The shrink schedule is picked, not measured.** → Halving rescues up to 8x over the
  ceiling. If a real oversized page still fails after three hops, raise `MAX_SEARCH_SHRINKS`;
  the schedule itself has no tuning constant left to get wrong.
- **A caller that ignores `truncated` reads a short page as a complete one.** → It previously
  got an error, so nothing regresses; the `_note` states it in prose the model reads, and the
  key is documented in the tool docstring.
- **`total` is Aleph's, not the page's.** → Already true of every search response, and the
  requirement says so explicitly.

## Migration Plan

Additive. No caller has to change: `truncated` and `continue_from_offset` are absent unless a
page was reduced, which today is an error. Rollback is reverting the commit.
