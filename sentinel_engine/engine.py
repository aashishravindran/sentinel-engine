# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.


from sentinel_engine.base import IdentityConnector, KnowledgeConnector


class AccessDeniedError(Exception):
    pass


class SentinelEngine:
    def __init__(self, identity: IdentityConnector, knowledge: KnowledgeConnector):
        self.identity = identity
        self.knowledge = knowledge

    async def secure_search(self, query: str, user_id: str, n_results: int = 5) -> list[dict]:
        tags = await self.identity.get_tags(user_id)

        # Fail-Closed: no tags = no access, no KB call made
        if not tags:
            raise AccessDeniedError(f"User '{user_id}' has no permissions. Access denied.")

        return await self.knowledge.search(query, tags, n_results)

    async def ingest(
        self,
        text: str,
        access_tags: list[str],
        doc_id: str,
        metadata: dict | None = None,
    ) -> None:
        await self.knowledge.ingest(text, access_tags, doc_id, metadata)
