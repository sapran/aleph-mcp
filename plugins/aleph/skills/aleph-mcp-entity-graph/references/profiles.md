# Profiles — the identity question already answered

Read this when a search hit or expansion result carries a **`profile_id`**. That is the trigger; on
an instance whose investigators have recorded no profiles, nothing here can fire.

A profile is an Aleph object in its own right — an EntitySet with a party, holding a recorded
identity decision that several entities are one actor. `get_profile` returns those constituents plus
a `merged` pseudo-entity combining their properties.

**Prefer the profile-scoped pivot over the entity-scoped one whenever a profile exists.** The entity
you happened to find is one fragment of the actor, so an ownership edge or a phone number recorded
on a different fragment is invisible from where you are standing:

- `get_profile` — the constituents and the merged view.
- `profile_tags` — shared phones, emails, addresses and names across the whole actor.
- `profile_similar` — what the identity decision left unresolved.
- `expand_profile` — graph neighbours of the actor rather than of one fragment.

All four take `profile_id`, never `entity_id`.

**A profile is a human decision, not ground truth.** It is scoped to a collection, it can be wrong,
and `profile_similar` shows you what it did not settle. Treat it as evidence that an investigator
judged the matter — stronger than a `similar_entities` score, weaker than an observation.
