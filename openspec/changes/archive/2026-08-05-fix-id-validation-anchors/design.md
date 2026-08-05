## Context

Three validation defects share one cause: the validators were written to be *sufficient to keep the guard safe* rather than *sufficient to describe the input*. All three fail closed — nothing reaches Aleph that should not — so the cost has been legibility, not exposure. That is exactly why they survived: nothing broke loudly.

The read-only guard in `readonly.py` matches with `re.fullmatch`. The validators in `client.py` use `re.match` with `$`. That mismatch is the whole bug.

## Goals / Non-Goals

**Goals:**

- Make the validators agree with the guard: `fullmatch` semantics, no trailing-character escape.
- One shared validator per id kind, with no inline bypass.
- Refuse ids that address nothing, so a caller is never answered from an endpoint other than the one it named.
- Retire the strict xfail and the spec's known-deviation note in the same change, so neither outlives the defect.

**Non-Goals:**

- `readonly.py`. Untouched. This change makes validation agree with the guard; it does not alter the guard. The `raw_path` question raised in `docs/implementation-notes.md` belongs to `baseline-read-only-guard`.
- Widening or narrowing the accepted id charset. `[A-Za-z0-9._:-]` stays as-is; only the anchoring and the empty-of-content case change.
- Anything about `refresh=true` or query strings.

## Decisions

### `re.fullmatch`, not `\Z`

Both fix the newline. `fullmatch` is chosen because it makes the validators textually match `readonly.py`, which already uses it — the point of the change is that these two agree, and that is easier to see when they read the same. `\Z` inside the pattern would fix the behaviour while leaving the two files looking different.

### Reject dot-only ids by content, not by pattern

Adding `.` to the excluded charset would break legitimate Aleph ids, which do contain dots. The refusal has to be about the id addressing nothing: an id whose every segment is `.` or `..` resolves, after URL normalisation, to some other path. Checking `value.strip('.')` is empty is sufficient and does not touch the charset.

Alternative considered: refuse any id containing `..`. Rejected — it would refuse a legitimate id that merely contains two consecutive dots, and the problem is not the substring, it is the id having no addressable content.

### `get_collection` calls the shared validator instead of matching inline

Currently `get_collection` branches on `_COLLECTION_ID.match(...)` directly, which is how it acquired the same `$` flaw independently. The fix is not to fix the inline match but to remove it: use `_COLLECTION_ID.fullmatch` for the *branch decision* (numeric-vs-foreign-id) and `_check_collection_id` for the *validation*, so there is one place where a collection id is judged.

The foreign-id branch stays unvalidated on purpose. That value goes into a `filter:foreign_id` query parameter, url-encoded by httpx, and cannot escape into the path. Validating it would reject legitimate foreign ids, which are free-form.

### The xfail comes out in this change, not later

`xfail(strict=True)` means a passing test fails the suite. So the fix cannot land without touching the marker — that was the point of choosing strict. The same applies to the spec note: the delta removes it by restating the requirement without it.

## Risks / Trade-offs

- **A previously-accepted input now raises.** Only inputs that already failed — illegibly, inside httpx — begin failing legibly. No input that produced a successful Aleph response changes behaviour. The mocked suite is the evidence; a full pass with no test edited except the xfail marker is the acceptance signal.
- **`entityset_items(".."`) changes from "returns an entity list" to "raises".** Technically a behaviour change for a caller relying on nonsense input. Accepted: answering a different question than the one asked is worse than refusing, and the spec now says so.
- **The charset is unchanged, so `%` is still excluded** — which is what keeps the decoded-vs-raw analysis valid. This change must not be read as having reviewed that; it has not. That review belongs to `baseline-read-only-guard`, and the note in `docs/implementation-notes.md` covering it stays.
