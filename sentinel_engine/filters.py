# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Deterministic filter builders: the only place access tags become query syntax.

Every adapter and connector builds filters here, so the MCP server and the
AgentCore interceptors push byte-identical filters into the knowledge base.
"""

import re
from collections.abc import Iterable, Mapping, Set
from typing import Any

from sentinel_engine.base import Chunk

TAG_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}")
TAG_KEY_PREFIX = "tag_"
ACCESS_TAGS_KEY = "access_tags"

# Grants admin rights in tag-based identity stores. Never valid on a document,
# and stripped from a user's retrieval scope.
ADMIN_TAG = "sentinel_admin"
RESERVED_TAGS = frozenset({ADMIN_TAG})


def is_valid_tag(tag: object) -> bool:
    return isinstance(tag, str) and TAG_PATTERN.fullmatch(tag) is not None


def normalize_tags(tags: Iterable[str]) -> list[str]:
    """Sorted, de-duplicated, validated tags. Raises ValueError on bad or empty input."""
    unique = set(tags)
    invalid = sorted(t for t in unique if not is_valid_tag(t))
    if invalid:
        raise ValueError(f"invalid access tags: {invalid}")
    if not unique:
        raise ValueError("at least one access tag is required")
    return sorted(unique)


def tag_key(tag: str) -> str:
    if not is_valid_tag(tag):
        raise ValueError(f"invalid access tag: {tag!r}")
    return f"{TAG_KEY_PREFIX}{tag}"


def build_bedrock_filter(tags: Iterable[str]) -> dict[str, Any]:
    """Bedrock Knowledge Bases metadata filter: match any of the caller's tags.

    An empty tag set raises instead of producing a filter that matches everything.
    """
    conditions: list[dict[str, Any]] = [
        {"equals": {"key": tag_key(tag), "value": True}} for tag in normalize_tags(tags)
    ]
    if len(conditions) == 1:
        return conditions[0]
    return {"orAll": conditions}


def build_vector_search_config(
    tags: Iterable[str], n_results: int, search_type: str = "HYBRID"
) -> dict[str, Any]:
    """retrievalConfiguration for a standard Bedrock KB Retrieve call."""
    return {
        "vectorSearchConfiguration": {
            "numberOfResults": n_results,
            "filter": build_bedrock_filter(tags),
            "overrideSearchType": search_type,
        }
    }


def build_managed_search_config(
    tags: Iterable[str], n_results: int, search_type: str = "HYBRID"
) -> dict[str, Any]:
    """retrievalConfiguration for a Managed KB reached through AgentCore Gateway."""
    return {
        "managedSearchConfiguration": {
            "numberOfResults": n_results,
            "filter": build_bedrock_filter(tags),
            "overrideSearchType": search_type,
        }
    }


def build_chroma_where(tags: Iterable[str]) -> dict[str, Any]:
    """ChromaDB where clause: match any of the caller's tags."""
    conditions: list[dict[str, Any]] = [
        {tag_key(tag): {"$eq": True}} for tag in normalize_tags(tags)
    ]
    if len(conditions) == 1:
        return conditions[0]
    return {"$or": conditions}


def document_tags(metadata: Mapping[str, Any]) -> frozenset[str]:
    """Tags a stored chunk was stamped with at ingest.

    ``access_tags`` is authoritative when present; otherwise fall back to
    ``tag_<name>: true`` keys. A chunk with neither has no tags.
    """
    raw = metadata.get(ACCESS_TAGS_KEY)
    if isinstance(raw, str):
        return frozenset(t for t in raw.split(",") if t)
    if isinstance(raw, list):
        return frozenset(str(t) for t in raw)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    return frozenset(
        key.removeprefix(TAG_KEY_PREFIX)
        for key, value in metadata.items()
        if key.startswith(TAG_KEY_PREFIX) and value is True
    )


def chunk_authorized(metadata: Mapping[str, Any], scope: Set[str]) -> bool:
    """Whether a retrieved chunk is visible to a caller with *scope*. Untagged means no."""
    return not document_tags(metadata).isdisjoint(scope)


def authorize_chunks(chunks: Iterable[Chunk], scope: Set[str]) -> list[Chunk]:
    """Drop any chunk the caller may not see.

    The filter is already pushed into the query; this re-check means a
    misconfigured or leaky store still cannot return an unauthorized chunk.
    """
    return [c for c in chunks if chunk_authorized(c["metadata"], scope)]
