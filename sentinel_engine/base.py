# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

from abc import ABC, abstractmethod


class IdentityConnector(ABC):
    @abstractmethod
    async def get_tags(self, user_id: str) -> set[str]:
        """Fetch permission tags for a user from the identity store."""


class KnowledgeConnector(ABC):
    @abstractmethod
    async def search(self, query: str, tags: set[str], n_results: int = 5) -> list[dict]:
        """Execute a tag-filtered vector search. Only returns documents whose
        access_tags intersect with the provided tags."""

    @abstractmethod
    async def ingest(
        self,
        text: str,
        access_tags: list[str],
        doc_id: str,
        metadata: dict | None = None,
    ) -> None:
        """Store a document with access_tags metadata attached."""
