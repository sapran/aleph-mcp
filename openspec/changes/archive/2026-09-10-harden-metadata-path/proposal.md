## Why

Work-plan item 1 in `docs/implementation-notes.md`: the instance-model path has one hard
failure and one silent one, and both were measured in the live tree at `develop @ b374900`
before this change was written.

**The hard one.** `get_model` caches `payload.get("model") or {}` with no type check, and
`_schemata` reads `model.get("schemata")` outside its own `try`. A metadata body like
`{"model": "https://..."}` therefore raises `AttributeError` where nothing catches it.
Measured: two consecutive `get_entity` calls both raised
`AttributeError: 'str' object has no attribute 'get'`, with the metadata route called
**once** — the bad value is cached, so all ten shaped tools plus `list_schemata`,
`get_schema` and the `aleph://schemata` resource stay broken for the process lifetime. It is
also the live counterexample to `_schemata`'s own comment, which reads an `AttributeError`
here as a defect in this module.

**The silent one.** `get_model` memoises only a success and `_schemata` swallows every
upstream fault, so a persistently broken `/api/2/metadata` is refetched on every
entity-returning call. Measured: three `get_entity` calls cost **12** metadata requests —
four transport retries each — and the reply carried no `_note`. Every other degradation in
this client announces itself (`TRUNCATED PAGE`, `EMPTY SLICE`, `EVERY COLLECTION`,
`_provenance`), but a caption derived from `_CAPTION_FALLBACK` is indistinguishable from one
the instance's own ontology produced.

The two halves are one change because they are two readings of the same value: what a
non-dict `model` *means* decides which of them handles it.

## What Changes

- A truthy non-dict `model` becomes an upstream refusal naming the JSON type received,
  raised where the bad value would have been cached, instead of an `AttributeError` from a
  later attribute access. A missing or empty `model` keeps its current meaning — an instance
  with no ontology to declare — and is still cached as `{}`.
- The failure to obtain a usable model is negatively cached for a bounded window, so a
  persistently broken metadata route costs one retry budget per window rather than one per
  entity-returning call. The window is bounded rather than permanent: a transient 503 must
  not degrade every caption for the process lifetime.
- A reply whose captions came from the fixed fallback order *because the ontology could not
  be read* carries a `_note` saying so. An ontology that was read and declares no caption
  fields is not a degradation and carries no note.
- Unchanged by design: the caption path still degrades rather than failing, so an unreadable
  ontology does not cost the caller ten tools; the ontology tools (`list_schemata`,
  `get_schema`, `aleph://schemata`) still surface the refusal, because for those an empty
  answer would be a lie about the instance.
