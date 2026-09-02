"""Payload builders shaped like a real Aleph, and the shape assertions both layers share.

Every mocked payload in this suite is a claim about what Aleph sends. A hand-rolled dict
that carries only the keys a test happens to assert on cannot catch a slimmer that starts
leaking `links` or `writeable`, because no fixture ever contained them. The builders here
carry the full observed key set instead, and `assert_slim_entity` / `assert_search_envelope`
encode the reshaped contract in one place so the mocked suite and `tests/live/` check the
same thing — see `test_live_responses_match_the_shape_the_mocked_suite_asserts`.
"""

import re
from typing import Any

BLOB_PROPS = ("bodyText", "bodyHtml", "safeHtml", "indexText", "translatedText")

# The untrusted-content fence get_entity_text wraps document text in. Matching the two
# markers against one backreference is the point: a nonce that differs between them, or
# a payload that forged a close marker, fails here rather than silently unwrapping.
_FENCE_RE = re.compile(
    r"\A<<<BEGIN UNTRUSTED DOCUMENT TEXT ([0-9a-f]{16})>>>\n(.*)\n"
    r"<<<END UNTRUSTED DOCUMENT TEXT \1>>>\Z",
    re.DOTALL,
)


def unfence(text: str) -> str:
    """Return the document text inside the fence, asserting the envelope is well formed."""
    m = _FENCE_RE.match(text)
    assert m is not None, f"text is not fenced: {text[:120]!r}"
    return m.group(2)


# Top-level keys a real Aleph search hit / entity GET carries, observed against a live
# instance. slim_entity must let none of them through except the ones it re-emits.
RAW_ONLY_KEYS = frozenset(
    {
        "links",
        "writeable",
        "mutable",
        "shallow",
        "latinized",
        "bookmarked",
        "created_at",
        "updated_at",
        "collection",
    }
)

SLIM_REQUIRED = frozenset({"id", "schema", "caption", "collection_id", "properties"})
SLIM_OPTIONAL = frozenset(
    {
        "highlight",
        "score",
        "profile_id",
        "first_seen",
        "last_seen",
        "_omitted_properties",
    }
)

# `searched` is search_entities' own addition and `_note`/`facets` are conditional, so the
# shared envelope requires only what every _slim_result caller emits.
ENVELOPE_REQUIRED = frozenset({"total", "limit", "offset", "results"})
ENVELOPE_OPTIONAL = frozenset({"searched", "facets", "_note", "truncated", "continue_from_offset"})


def raw_entity(
    *,
    id: str = "e1",
    schema: str = "Person",
    properties: dict[str, Any] | None = None,
    collection_id: str = "42",
    **extra: Any,
) -> dict[str, Any]:
    """An entity in the shape Aleph really serialises: nested `collection`, no caption,
    plus the housekeeping keys the slimmer must drop.

    `collection` is nested and `collection_id` absent because that is what a live search
    hit looks like, and `_collection_id` in client.py reads exactly that nesting.
    """
    entity: dict[str, Any] = {
        "id": id,
        "schema": schema,
        "caption": None,
        "properties": {"name": ["Jane Doe"]} if properties is None else properties,
        "collection": {
            "id": collection_id,
            "label": "Case files",
            "foreign_id": "case",
            "links": {"self": f"/api/2/collections/{collection_id}"},
            "shallow": True,
        },
        "links": {"self": f"/api/2/entities/{id}"},
        "writeable": False,
        "mutable": False,
        "shallow": False,
        "latinized": {"names": ["Jane Doe"]},
        "bookmarked": False,
        "created_at": "2026-01-01T00:00:00.000000",
        "updated_at": "2026-01-02T00:00:00.000000",
    }
    entity.update(extra)
    return entity


def raw_document(*, id: str = "d1", **extra: Any) -> dict[str, Any]:
    """raw_entity with schema="Document", fileName, and every BLOB_PROPS key populated."""
    props: dict[str, Any] = {"name": ["Memo"], "fileName": ["memo.pdf"]}
    props.update({p: [f"<{p} body>"] for p in BLOB_PROPS})
    props.update(extra.pop("properties", None) or {})
    return raw_entity(id=id, schema="Document", properties=props, **extra)


def raw_search_payload(
    *results: dict[str, Any],
    total: int = 1,
    total_type: str = "eq",
    facets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The real search envelope, including the keys the client is expected to discard."""
    limit = len(results)
    payload: dict[str, Any] = {
        "status": "ok",
        "total": total,
        "total_type": total_type,
        "page": 1,
        "pages": 1 if limit == 0 else -(-total // limit),
        "limit": limit,
        "offset": 0,
        "next": None,
        "previous": None,
        "query_text": None,
        "links": {"self": "/api/2/entities"},
        "results": list(results),
    }
    if facets:
        payload["facets"] = facets
    return payload


def raw_model() -> dict[str, Any]:
    """One FtM metadata payload, the single copy test_client and test_resources share.

    Person is matchable, Ownership is the edge; Pages extends Document so a text-carrying
    branch exists for the get_entity_text cases.
    """
    return {
        "model": {
            "schemata": {
                "Person": {
                    "label": "Person",
                    "matchable": True,
                    "schemata": ["Person", "LegalEntity", "Thing"],
                    "extends": ["LegalEntity"],
                    "caption": ["name"],
                    "properties": {"name": {"label": "Name", "type": "name"}},
                },
                "Document": {
                    "label": "Document",
                    "schemata": ["Document", "Thing"],
                    "extends": ["Thing"],
                    "caption": ["fileName", "title"],
                    "properties": {
                        "fileName": {"label": "File name", "type": "string"},
                        "bodyText": {"label": "Text", "type": "text"},
                    },
                },
                "Pages": {
                    "label": "Pages",
                    "schemata": ["Pages", "Document", "Thing"],
                    "extends": ["Document"],
                    "caption": ["fileName", "title"],
                    "properties": {"fileName": {"label": "File name", "type": "string"}},
                },
                "Ownership": {
                    "label": "Ownership",
                    "edge": {"source": "owner", "target": "asset", "directed": True},
                    "properties": {
                        "owner": {"label": "Owner", "type": "entity", "range": "LegalEntity"},
                        "asset": {"label": "Asset", "type": "entity", "range": "Thing"},
                    },
                },
            }
        }
    }


def assert_slim_entity(e: dict[str, Any]) -> None:
    """The reshaped entity contract: nothing but the slim key set, no document bodies.

    `caption` may be null — live Aleph sends null captions and derive_caption legitimately
    returns None when no fallback property is present.
    """
    keys = set(e)
    assert keys <= SLIM_REQUIRED | SLIM_OPTIONAL, (
        f"unexpected keys: {keys - SLIM_REQUIRED - SLIM_OPTIONAL}"
    )
    assert SLIM_REQUIRED <= keys, f"missing keys: {SLIM_REQUIRED - keys}"
    assert not keys & RAW_ONLY_KEYS, f"raw Aleph keys leaked: {keys & RAW_ONLY_KEYS}"
    props = set(e["properties"] or {})
    assert not props & set(BLOB_PROPS), f"document text leaked: {props & set(BLOB_PROPS)}"


def assert_search_envelope(
    out: dict[str, Any], *, searched: dict[str, str | None] | None = None
) -> None:
    """The reshaped result envelope shared by every `_slim_result` caller.

    Pass `searched` to also pin the scope search_entities reports; the other callers
    (entityset_items, match_entity) do not emit that key.
    """
    keys = set(out)
    assert keys <= ENVELOPE_REQUIRED | ENVELOPE_OPTIONAL, (
        f"unexpected keys: {keys - ENVELOPE_REQUIRED - ENVELOPE_OPTIONAL}"
    )
    assert ENVELOPE_REQUIRED <= keys, f"missing keys: {ENVELOPE_REQUIRED - keys}"
    if searched is not None:
        assert out["searched"] == searched
    for result in out["results"]:
        assert_slim_entity(result)
