## Context

The twelve shipped tools reached Aleph's identity *candidates* but not its identity *decisions*.
Aleph models the decision as a profile: `EntitySet` with discriminator `type == "profile"` and a
party, holding constituent entities plus a merged pseudo-entity. Discovery was already wired —
Aleph indexes `profile_id` on entities and `slim_entity` passed it through — so the surface was
advertising an object it could not read.

Two constraints shaped the design. Aleph's profile routes live under `/api/2/profiles/`, not
under `/entities/`, so nothing could be added as a sub-resource of the existing entity cluster.
And a profile id *is* an entityset id, which makes `GET /api/2/entitysets/<id>` redirect into the
profile view — coupling the two capabilities at the transport level.

## Goals / Non-Goals

**Goals.** Make a recorded identity decision readable, with the same pivots the entity cluster
already offers. Keep every response bounded under the existing no-document-text guarantee. Widen
the allowlist by exactly the GET paths those tools need. Stop the server asserting a query
semantic Aleph does not implement.

**Non-Goals.** No write capability, including judgement recording. No new transport, auth mode or
configuration. No change to the unprefixed-name posture. No client-side identity resolution: this
change reads Aleph's decision, it does not compute one.

## Decisions

### Reconcile was evaluated and rejected as redundant

Recorded because "wrap reconcile" is the obvious next suggestion and re-deriving the answer costs
a source read.

There is no bare `GET /api/2/reconcile`. The real routes are `/api/freebase/reconcile` and
`GET|POST /api/2/collections/<collection_id>/reconcile` (`reconcile_api.py:96-99`). Decisively,
`reconcile_op` builds `MatchQuery(parser, entity=proxy)` at `reconcile_api.py:171` — the same
engine as `POST /api/2/match` (`entities_api.py:222`), which is already wrapped as
`match_entity`, under the same `can_browse_anonymous` permission (`:131` vs `:217`).

It differs only in taking a bare string instead of a one-line FtM fragment, and in returning a
worse shape: `r:score` instead of `score`, `type` as an array of freebase-type objects, and
`match` hardcoded `False` (`reconcile_api.py:41-51`).

So it buys no capability. The genuine gain people attribute to it — tolerant name lookup — is
already `match_entity`. What was actually missing was the server *saying* that `q` is not that
path, which is why the `INSTRUCTIONS` and README correction is in this change and a reconcile
tool is not.

Also rejected, with reasons, so the same endpoints are not re-proposed:

- `GET /api/2/statistics` (`base_api.py:131`) — `get_collection` already returns the
  per-collection denominator any method actually uses.
- `POST /api/2/profiles/_pairwise` (`profiles_api.py:207`) — a write. See the allowlist decision.
- `_stream` (`stream_api.py:54` requires WRITE; global form `:56` requires admin) and mapping
  detail (`mappings_api.py:178` requires WRITE despite being a GET) — outside a read-scoped key.
- alerts, notifications, status, bookmarks, exports — `logged_in`-gated per-user UI state, not
  target intelligence.
- `GET /api/2/archive?claim=` (`archive_api.py:12`) — raw source-file download, which is the
  opposite of the bounding discipline every other tool enforces.

### The method pin, not the path pattern, is what refuses `_pairwise`

`_ENTITY_ID` is `[A-Za-z0-9._:-]+`, which admits `_`. So the GET rule for
`/api/2/profiles/<id>` also matches the *path* of `POST /api/2/profiles/_pairwise`, an Aleph
write that records a judgement and can create or merge a profile. It stays unreachable only
because the allowlist pairs a method with each path and no POST profile rule was added.

Two alternatives were considered and rejected:

1. **Narrow the id pattern to `[0-9a-f]{32}`.** Ids are only *conventionally* `uuid4().hex`; the
   column is `db.String(128)` (`aleph/model/entityset.py:45`). Narrowing trades a
   theoretical tightening for a real availability bug on any instance that ever minted an id
   another way, and it would silently refuse legitimate reads.
2. **Add an explicit negative rule for `_pairwise`.** This inverts the allowlist's design — it is
   a closed positive list precisely so that nothing has to be enumerated as forbidden. One
   negative entry invites the next, and the file stops being auditable by reading it.

Chosen instead: leave the pattern and the positive-list design alone, document the coupling in a
comment at the pattern definition, assert it in a named test
(`test_pairwise_judgement_is_blocked`, which checks GET-allowed *and* POST-refused so the
refusal is attributable to the method), and record it in the `read-only-guard` requirement prose
so a future reader does not "simplify" the method half away.

### `merged` must be slimmed, which is not obvious from its name

A merged proxy inherits the properties of every constituent entity. If any constituent is a
`Document`, `merged` carries its `bodyText`. The no-document-sized-text requirement is written
about entities in responses, and `merged` is one, so passing it through raw would have violated a
shipped requirement through a field that does not look like a search hit. `slim_entity` handles
it, and as a side effect drops the serializer's `latinized` block — a transliteration of names
already present in `properties`, so pure context cost.

### `get_entityset` returns a profile sometimes, and says so

`GET /api/2/entitysets/<id>` 302-redirects to `/api/2/profiles/<id>` for profile-type sets
(`entitysets_api.py:118-120`). Pre-fetching to detect the type before choosing a route was
rejected: it doubles the request count for every call to defend against a case Aleph already
signals in the response body. Instead the tool detects `type == "profile"` after the fact and
sets `_note`, reusing the convention `search_entities` already uses for an unenumerable result
set.

This makes the redirect load-bearing for the allowlist: the guard runs on every hop, so
`get_entityset` works for profiles only because `/api/2/profiles/<id>` is listed. That coupling
is now a stated requirement rather than an accident, because a future narrowing of the profile
rules would break `get_entityset` and the connection is not visible from either file alone.

### Naming: mirror the object, not the existing inconsistency

The entity cluster is already inconsistent (`entity_tags` beside `similar_entities`). Rather than
propagate it, the new tools mirror the *object* they address: `get_profile` beside `get_entity`
and `get_collection`; `profile_tags` beside `entity_tags`; `expand_profile` beside
`expand_entity`; `get_entityset` beside `list_entitysets` as `get_collection` sits beside
`list_collections`.

`profile_similar` is the one deliberate departure. `similar_profiles` would be a misnomer: the
endpoint returns *entities* similar to the profile, not similar profiles. The `profile_`-prefixed
form avoids asserting the wrong return type, at the cost of not matching `similar_entities`
exactly.

## Risks / Trade-offs

- **Five more tools is five more descriptions competing for model attention.** Mitigated by
  folding the cluster into `INSTRUCTIONS` step 4 as a conditional — use these *when a result
  carries `profile_id`* — rather than presenting them as a parallel workflow.
- **`expand_profile` refuses above 200 where Aleph would clamp.** Deliberately stricter than the
  server, matching `expand_entity`: a clamped expansion silently looks like a complete one, and
  the whole surface's posture is to refuse rather than truncate quietly.
- **An instance with no judged cross-references has no profiles**, so the live test skips rather
  than fails. Accepted: the alternative is a test that fails on a correctly-configured Aleph.
  The mocked suite covers shape; the skip is honest about what a given instance can prove.
