from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ResourceError, ToolError

from .client import MAX_EXPAND, MAX_PAGE, AlephClient
from .config import Settings

INSTRUCTIONS = f"""
Read-only access to an Aleph instance (OCCRP investigative data platform).

Aleph stores a graph of FollowTheMoney (FtM) entities — Person, Company, Ownership,
Document, Email and so on — grouped into collections (investigations and datasets).
Entities carry typed properties; properties whose type is `entity` are the graph edges.

Working method that fits Aleph's limits:

1. `list_collections` to see what this key can read, then `get_collection` for stats.
2. `search_entities` with `facets=[...]` and `limit=0` FIRST, to learn how a result set
   breaks down before pulling rows. Useful facets: schema, collection_id, countries,
   languages, mime_type, dates.
3. Narrow with `filters` (exact-match, AND across keys, OR within a list) and only then
   raise `limit`.
   Search is always scoped to a schema branch: `schemata="Thing"` is applied by default
   (people, companies, addresses, documents). Relationships — Ownership, Directorship,
   Payment, UnknownLink — descend from `Interval` and must be asked for by name.
4. Pivot on a specific entity with `expand_entity` (graph neighbours), `entity_tags`
   (other entities sharing an email/phone/address), `similar_entities` and
   `xref_results` (candidate duplicates across collections). When a result carries a
   `profile_id`, the identity question is already answered for it: an investigator
   recorded that several entities are one actor, so use `get_profile`, `profile_tags`,
   `profile_similar` and `expand_profile` to work the merged identity rather than the
   one fragment you happened to find.
5. Read document text last, with `get_entity_text`, in bounded slices.

Hard limits, which are Aleph's and cannot be worked around by paging:
- `limit + offset` may never exceed {MAX_PAGE} on search. Deep pagination is not a way to
  read a whole collection; narrow the query or facet instead.
- `expand_entity` has a separate, much lower ceiling of {MAX_EXPAND} per property.
- Search text (`q`) is an Elasticsearch query_string — `"exact phrase"`, AND/OR/NOT,
  field:value and wildcards all work. It is NOT fuzzy: a misspelt or transliterated name
  will not match. Use `match_entity` for name lookup. Multi-term `q` requires only 66% of
  terms to match, so narrow with `filters`, not by adding words.

This server exposes no way to create, modify, ingest or delete anything: every outgoing
request is checked against a fixed allowlist of Aleph read endpoints and refused before it
is sent, whatever the API key is allowed to do. For bulk export
of a whole collection, use the separate `aleph-coldbackup` tool, which needs a
write-scoped key that this server intentionally does not require.
""".strip()


def build_server(settings: Settings) -> tuple[FastMCP, AlephClient]:
    """Construct a configured FastMCP server and its AlephClient.

    Returns both so the caller owns the client lifetime and can close it on shutdown.
    """
    mcp: FastMCP = FastMCP(name="aleph-mcp", instructions=INSTRUCTIONS)
    client = AlephClient(settings)

    @mcp.tool
    async def list_collections(q: str | None = None, limit: int = 30) -> dict[str, Any]:
        """List the Aleph collections (investigations and datasets) this key can read.

        `q` filters by label text. Returns each collection's numeric `id` — the value
        every other tool wants — alongside its human `foreign_id` and `label`.
        """
        try:
            return await client.list_collections(q=q, limit=limit)
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def get_collection(collection: str) -> dict[str, Any]:
        """Fetch one collection with its statistics, by numeric id or by foreign_id.

        `statistics` breaks the collection down by schema, country and language — read
        it before searching, to know what the data actually contains.
        """
        try:
            return await client.get_collection(collection=collection)
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def search_entities(
        q: str | None = None,
        filters: dict[str, str | list[str]] | None = None,
        schema: str | None = None,
        schemata: str | None = None,
        facets: list[str] | None = None,
        facet_size: int = 20,
        limit: int = 20,
        offset: int = 0,
        highlight: bool = False,
    ) -> dict[str, Any]:
        """Search entities across every readable collection.

        - `q`: Elasticsearch query_string. Quote phrases; AND/OR/NOT and wildcards work.
        - `filters`: exact-match constraints, e.g.
          {"collection_id": "42", "countries": ["ru", "cy"]}. Different keys are ANDed,
          values within one list are ORed. Common keys: collection_id, countries,
          languages, emails, phones, names, addresses, mime_type, dates, file_name.
        - `schema`: match one exact FtM schema ("Person"). `schemata`: match a schema and
          everything below it ("LegalEntity" also returns Company and Person).
          Aleph *requires* one of these — it selects the search index — so when you give
          neither, `schemata="Thing"` is applied, matching the Aleph UI's general search.
          `Thing` covers Person, Company, Address, Document, Email and similar. It does
          NOT cover relationships: Ownership, Directorship, Payment and UnknownLink
          descend from `Interval`, so ask for `schemata="Interval"` or name the schema.
          Every result reports the scope it actually searched under `searched`.
        - `facets`: request bucket counts, e.g. ["schema", "collection_id", "countries"].
          Combine with limit=0 to survey a result set for free before pulling rows.
        - `highlight`: return matching snippets; only meaningful together with `q`.

        Document-sized text properties are stripped from results — use get_entity_text.
        """
        try:
            return await client.search_entities(
                q=q,
                filters=filters,
                schema=schema,
                schemata=schemata,
                facets=facets,
                facet_size=facet_size,
                limit=limit,
                offset=offset,
                highlight=highlight,
            )
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def get_entity(entity_id: str) -> dict[str, Any]:
        """Fetch one entity by id, with its properties and caption.

        Text bodies are omitted here; `_omitted_properties` names what was left out.
        """
        try:
            return await client.get_entity(entity_id=entity_id)
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def expand_entity(
        entity_id: str, properties: list[str] | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """Traverse the graph: return entities adjacent to this one, grouped by property.

        This is how you walk ownership, directorship, membership, family, email
        correspondence and document containment. `properties` restricts the traversal to
        named edges (e.g. ["ownershipOwner", "directorshipDirector"]); omit it to follow
        every edge. Each group reports a `count`, so a truncated group tells you the real
        degree even when the entities are capped.

        Ceiling is 200 entities per property (client.MAX_EXPAND) — far lower than search's.
        """
        try:
            return await client.expand_entity(
                entity_id=entity_id, properties=properties, limit=limit
            )
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def entity_tags(entity_id: str) -> dict[str, Any]:
        """Count other entities that share this one's property values.

        The cheapest pivot in Aleph: it answers "who else uses this phone number, email,
        address or name" without a search, and returns the query to run for each hit.
        """
        try:
            return await client.entity_tags(entity_id=entity_id)
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def similar_entities(entity_id: str, limit: int = 20) -> dict[str, Any]:
        """Find probable duplicates of an entity, scored, with any human judgement made.

        Use for identity resolution: the same person or company recorded twice under
        different spellings, in the same or a different collection.
        """
        try:
            return await client.similar_entities(entity_id=entity_id, limit=limit)
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def match_entity(
        sample: dict[str, Any],
        collection_ids: list[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Look up a person or company you describe, rather than one already in Aleph.

        `sample` is an FtM entity fragment, e.g.
        {"schema": "Person", "properties": {"name": ["Jane Doe"], "birthDate": ["1970"]}}.
        Use this to check an externally-obtained name against the whole index.
        """
        try:
            return await client.match_entity(
                sample=sample, collection_ids=collection_ids, limit=limit
            )
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def get_profile(profile_id: str) -> dict[str, Any]:
        """Read a resolved identity: the entities an investigator decided are one actor.

        A profile is Aleph's *recorded* identity decision, not a scored guess — several
        entities, possibly held in different collections, asserted to be the same
        real-world person or company. `entities` lists the constituents; `merged` is the
        synthesised pseudo-entity combining their properties, so it is the fullest single
        view of the actor that Aleph holds.

        You do not need a lookup tool to find one: search hits and expansion results
        carry a `profile_id` field whenever the entity belongs to a profile. When they
        do, prefer the profile-scoped tools — an entity is one fragment of the actor.
        """
        try:
            return await client.get_profile(profile_id=profile_id)
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def profile_tags(profile_id: str) -> dict[str, Any]:
        """Count other entities sharing a resolved identity's property values.

        `entity_tags` against the merged identity rather than one of its fragments, so a
        phone or address contributed by any constituent entity is pivoted on here.
        """
        try:
            return await client.profile_tags(profile_id=profile_id)
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def profile_similar(profile_id: str, limit: int = 20) -> dict[str, Any]:
        """Find entities still unresolved against this identity, scored.

        These are the candidates the existing merge did not absorb — the remaining
        identity question after a human already answered part of it.
        """
        try:
            return await client.profile_similar(profile_id=profile_id, limit=limit)
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def expand_profile(
        profile_id: str, properties: list[str] | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """Traverse the graph from a resolved identity, grouped by property.

        `expand_entity` against the merged identity: it returns neighbours reached
        through any constituent entity, so an ownership edge recorded on only one of the
        duplicates still shows up here.

        Ceiling is 200 entities per property (client.MAX_EXPAND), as for expand_entity.
        """
        try:
            return await client.expand_profile(
                profile_id=profile_id, properties=properties, limit=limit
            )
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def list_entitysets(
        collection_id: str, set_type: str | None = None, limit: int = 30
    ) -> dict[str, Any]:
        """List the curated sets in a collection: lists, network diagrams and timelines.

        These encode what human investigators already decided matters. Read them before
        re-deriving the same structure yourself. `set_type` filters to one of
        "list", "diagram", "timeline".
        """
        try:
            return await client.list_entitysets(
                collection_id=collection_id, set_type=set_type, limit=limit
            )
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def get_entityset(entityset_id: str) -> dict[str, Any]:
        """Fetch one curated set's own record: what it is, who made it, when.

        `entityset_items` returns a set's contents; this returns the set itself, which is
        where the curator's intent lives — its type, label and summary. Profiles are a
        kind of entityset, so a profile id passed here comes back as a profile, flagged
        in `_note`; call get_profile for those instead.
        """
        try:
            return await client.get_entityset(entityset_id=entityset_id)
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def entityset_items(
        entityset_id: str, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        """Return the entities belonging to one curated set."""
        try:
            return await client.entityset_items(
                entityset_id=entityset_id, limit=limit, offset=offset
            )
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def xref_results(collection_id: str, limit: int = 30, offset: int = 0) -> dict[str, Any]:
        """Read existing cross-reference matches between this collection and others.

        Cross-referencing is how an investigation is linked to sanctions lists, company
        registries and other datasets. This reads results already computed on the server;
        it cannot start a new cross-reference run. Empty means none has been run.
        """
        try:
            return await client.xref_results(
                collection_id=collection_id, limit=limit, offset=offset
            )
        except ValueError as e:
            raise ToolError(str(e)) from e

    @mcp.tool
    async def get_entity_text(
        entity_id: str, offset: int = 0, limit: int = 20000
    ) -> dict[str, Any]:
        """Read a bounded slice of a document's extracted text.

        `total_chars` and `truncated` tell you whether to fetch further slices by raising
        `offset`. Read deliberately: a long document consumes the context you need for
        analysis. Prefer search with `highlight=True` when you only need to confirm that a
        term occurs and see it in context.
        """
        try:
            return await client.get_entity_text(entity_id=entity_id, offset=offset, limit=limit)
        except ValueError as e:
            raise ToolError(str(e)) from e

    # -- resources -------------------------------------------------------------

    @mcp.resource("aleph://collections", mime_type="application/json")
    async def collections_resource() -> dict[str, Any]:
        """Browsable list of readable collections (mirrors list_collections)."""
        return await client.list_collections(limit=100)

    @mcp.resource("aleph://schemata", mime_type="application/json")
    async def schemata_resource() -> dict[str, Any]:
        """Every FollowTheMoney schema this instance knows, split into matchable and edge types."""
        return await client.list_schemata()

    @mcp.resource("aleph://schema/{name}", mime_type="application/json")
    async def schema_resource(name: str) -> dict[str, Any]:
        """One FtM schema: its inheritance chain, properties, types and graph edges.

        Read this before writing a filter or an expand call against an unfamiliar schema.
        """
        try:
            return await client.get_schema(name=name)
        except ValueError as e:
            raise ResourceError(str(e)) from e

    return mcp, client
