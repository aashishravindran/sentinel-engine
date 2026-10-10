# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

import asyncio
from collections.abc import Mapping, Set
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer

from sentinel_engine.base import Chunk, KnowledgeConnector, MetadataValue
from sentinel_engine.filters import build_chroma_where
from sentinel_engine.ingest.stamp import stamp_metadata, validate_doc_id


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

    async def search(self, query: str, tags: Set[str], n_results: int = 5) -> list[Chunk]:
        embedding = await asyncio.to_thread(self._embed, query)
        where: Any = build_chroma_where(tags)

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

        docs = (results["documents"] or [[]])[0]
        metas = (results["metadatas"] or [[]])[0]
        distances = (results["distances"] or [[]])[0]

        return [
            {"text": doc, "metadata": dict(meta), "score": round(1 - dist, 4)}
            for doc, meta, dist in zip(docs, metas, distances, strict=True)
        ]

    async def ingest(
        self,
        text: str,
        access_tags: list[str],
        doc_id: str,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> None:
        doc_id = validate_doc_id(doc_id)
        meta: Any = stamp_metadata(access_tags, metadata)
        embedding = await asyncio.to_thread(self._embed, text)

        await asyncio.to_thread(
            self._collection.upsert,
            ids=[doc_id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[meta],
        )
