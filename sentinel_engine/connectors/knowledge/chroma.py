# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

import asyncio

import chromadb
from sentence_transformers import SentenceTransformer

from sentinel_engine.base import KnowledgeConnector


class ChromaKnowledgeConnector(KnowledgeConnector):
    """
    ChromaDB-backed knowledge store with local sentence-transformer embeddings.

    Access control uses a single OR filter: a document is returned if the user
    holds at least one of the document's access_tags. A document tagged
    [finance, engineering] is accessible to users with finance OR engineering.

    Tag storage: each access tag is a boolean metadata field `tag_{name}: True`,
    plus a human-readable `access_tags` comma-separated string.

    Example stored metadata:
        {"tag_finance": True, "tag_engineering": True, "access_tags": "finance,engineering"}
    """

    def __init__(self, path: str, collection_name: str, embedding_model: str):
        self._model = SentenceTransformer(embedding_model)
        self._client = chromadb.PersistentClient(path=path)
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def _embed(self, text: str) -> list[float]:
        return self._model.encode(text).tolist()

    def _build_where_filter(self, tags: set[str]) -> dict:
        """OR filter: retrieve docs where the user holds at least one access tag."""
        tag_conditions = [{f"tag_{tag}": {"$eq": True}} for tag in tags]
        if len(tag_conditions) == 1:
            return tag_conditions[0]
        return {"$or": tag_conditions}

    async def search(self, query: str, tags: set[str], n_results: int = 5) -> list[dict]:
        embedding = await asyncio.to_thread(self._embed, query)
        where = self._build_where_filter(tags)

        try:
            results = await asyncio.to_thread(
                self._collection.query,
                query_embeddings=[embedding],
                n_results=n_results,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            if "Number of requested results" in str(e):
                results = await asyncio.to_thread(
                    self._collection.query,
                    query_embeddings=[embedding],
                    n_results=1,
                    where=where,
                    include=["documents", "metadatas", "distances"],
                )
            else:
                raise

        docs = results["documents"][0]
        metas = results["metadatas"][0]
        distances = results["distances"][0]

        return [
            {
                "text": doc,
                "metadata": meta,
                "score": round(1 - dist, 4),
            }
            for doc, meta, dist in zip(docs, metas, distances, strict=True)
        ]

    async def ingest(
        self,
        text: str,
        access_tags: list[str],
        doc_id: str,
        metadata: dict | None = None,
    ) -> None:
        embedding = await asyncio.to_thread(self._embed, text)

        meta = dict(metadata or {})
        for tag in access_tags:
            meta[f"tag_{tag}"] = True
        meta["access_tags"] = ",".join(access_tags)

        await asyncio.to_thread(
            self._collection.upsert,
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[meta],
        )
