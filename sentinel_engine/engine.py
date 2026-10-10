# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

from collections.abc import Mapping

from sentinel_engine.authz import AdminPolicy, default_admin_policy
from sentinel_engine.base import Chunk, IdentityConnector, KnowledgeConnector, MetadataValue
from sentinel_engine.errors import AccessDeniedError
from sentinel_engine.filters import RESERVED_TAGS, authorize_chunks, is_valid_tag
from sentinel_engine.principal import Principal, validate_subject
from sentinel_engine.telemetry import timed

__all__ = ["AccessDeniedError", "SentinelEngine"]


class SentinelEngine:
    """Policy decision point: who may read what, resolved live on every call."""

    def __init__(
        self,
        identity: IdentityConnector,
        knowledge: KnowledgeConnector,
        *,
        admin_policy: AdminPolicy | None = None,
    ):
        self.identity = identity
        self.knowledge = knowledge
        self.admin_policy = admin_policy or default_admin_policy(identity)

    async def resolve_scope(self, user_id: str) -> frozenset[str]:
        """The tags *user_id* may read right now. Never cached; raises rather than widening."""
        user_id = validate_subject(user_id)
        try:
            with timed("identity"):
                raw = await self.identity.get_tags(user_id)
        except AccessDeniedError:
            raise
        except Exception as exc:
            raise AccessDeniedError("identity lookup failed. Access denied.") from exc

        scope = frozenset(t for t in raw if is_valid_tag(t) and t not in RESERVED_TAGS)
        # Fail closed: no tags means no access, and the knowledge base is never queried.
        if not scope:
            raise AccessDeniedError(f"User '{user_id}' has no permissions. Access denied.")
        return scope

    async def secure_search(
        self, query: str, principal: Principal | str, n_results: int = 5
    ) -> list[Chunk]:
        user_id = principal.user_id if isinstance(principal, Principal) else principal
        scope = await self.resolve_scope(user_id)
        with timed("kb"):
            chunks = await self.knowledge.search(query, scope, n_results)
        with timed("postfilter"):
            return authorize_chunks(chunks, scope)

    async def is_admin(self, principal: Principal | str) -> bool:
        user_id = principal.user_id if isinstance(principal, Principal) else principal
        return await self.admin_policy.is_admin(validate_subject(user_id))

    async def ingest(
        self,
        text: str,
        access_tags: list[str],
        doc_id: str,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> None:
        await self.knowledge.ingest(text, access_tags, doc_id, metadata)
