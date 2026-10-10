# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Validate what gets written into the knowledge base, and stamp its access tags.

Connectors call these before every write, so a caller can neither smuggle a
path into a storage key nor overwrite the tags that control who reads a chunk.
"""

import re
from collections.abc import Iterable, Mapping

from sentinel_engine.base import MetadataValue
from sentinel_engine.filters import (
    ACCESS_TAGS_KEY,
    RESERVED_TAGS,
    TAG_KEY_PREFIX,
    normalize_tags,
    tag_key,
)

DOC_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}")
METADATA_KEY_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")


def validate_doc_id(doc_id: object) -> str:
    """A document ID safe to use as a storage key (no slashes, no leading dot)."""
    if not isinstance(doc_id, str) or not DOC_ID_PATTERN.fullmatch(doc_id):
        raise ValueError(f"invalid doc_id: {doc_id!r}")
    return doc_id


def validate_access_tags(tags: Iterable[str]) -> list[str]:
    """Tags for a document: at least one, all valid, none reserved."""
    normalized = normalize_tags(tags)
    reserved = sorted(RESERVED_TAGS.intersection(normalized))
    if reserved:
        raise ValueError(f"reserved tags cannot be assigned to documents: {reserved}")
    return normalized


def stamp_metadata(
    access_tags: Iterable[str], metadata: Mapping[str, object] | None = None
) -> dict[str, MetadataValue]:
    """Caller metadata plus Sentinel's access stamp, which the caller cannot override."""
    tags = validate_access_tags(access_tags)
    stamped: dict[str, MetadataValue] = {}
    for key, value in (metadata or {}).items():
        if not METADATA_KEY_PATTERN.fullmatch(key):
            raise ValueError(f"invalid metadata key: {key!r}")
        if key == ACCESS_TAGS_KEY or key.startswith(TAG_KEY_PREFIX):
            raise ValueError(f"metadata key {key!r} is reserved for access control")
        if not isinstance(value, str | int | float | bool):
            raise ValueError(f"metadata value for {key!r} must be a string, number or boolean")
        stamped[key] = value
    for tag in tags:
        stamped[tag_key(tag)] = True
    stamped[ACCESS_TAGS_KEY] = ",".join(tags)
    return stamped
