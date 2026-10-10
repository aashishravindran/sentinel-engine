# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

import json
from collections.abc import Mapping, Set
from typing import Any

import aioboto3

from sentinel_engine.base import Chunk, KnowledgeConnector, MetadataValue
from sentinel_engine.filters import build_vector_search_config
from sentinel_engine.ingest.stamp import stamp_metadata, validate_doc_id

# Default reranking model — Amazon Rerank 1.0 (cross-encoder, no extra cost beyond API calls)
_DEFAULT_RERANK_MODEL = "arn:aws:bedrock:{region}::foundation-model/amazon.rerank-v1:0"


class BedrockKnowledgeConnector(KnowledgeConnector):
    """
    AWS Bedrock Knowledge Bases connector with ABAC tag filtering,
    hybrid search, and optional reranking.

    Search modes (search_type):
        "SEMANTIC" — dense vector search only (default Bedrock behaviour).
        "HYBRID"   — combines dense vector + keyword (BM25) search, then merges
                     results with Reciprocal Rank Fusion (RRF). Requires the KB
                     to have been created with a vector store that supports hybrid
                     search (e.g. OpenSearch Serverless with hybrid index).

    Reranking (reranking=True):
        After retrieval, sends candidates to a Bedrock cross-encoder reranking
        model (default: amazon.rerank-v1:0) which rescores and reorders results
        by relevance to the query. To avoid the reranker seeing too few candidates,
        retrieval fetches n_results * rerank_oversample docs first, then the
        reranker reduces the list back to n_results.

    Access control: OR-policy metadata filter — a document tagged
    [finance, engineering] is returned if the user holds finance OR engineering.

    Tag storage: each access tag stored as a boolean metadata attribute
    `tag_{name}: true` in a .metadata.json sidecar file alongside the document
    in S3.

    Ingestion: uploads document text to S3, writes the metadata sidecar, then
    optionally triggers a Bedrock KB ingestion job (if data_source_id is set).

    Environment variables (read by sentinel_engine.factory):
        BEDROCK_KB_ID           — Knowledge Base ID
        BEDROCK_S3_BUCKET       — S3 bucket backing the KB data source
        BEDROCK_S3_PREFIX       — S3 key prefix for documents (default: "documents/")
        BEDROCK_DS_ID           — Data Source ID for triggering sync (optional)
        BEDROCK_SEARCH_TYPE     — "HYBRID" or "SEMANTIC" (default: "HYBRID")
        BEDROCK_RERANKING       — "true" to enable reranking (default: "false")
        BEDROCK_RERANK_MODEL_ARN — Full ARN of reranking model (default: amazon.rerank-v1:0)
        BEDROCK_RERANK_OVERSAMPLE — Candidate multiplier for reranking (default: "3")
        AWS_REGION              — AWS region (default: "us-east-1")
    """

    def __init__(
        self,
        kb_id: str,
        s3_bucket: str,
        s3_prefix: str = "documents/",
        data_source_id: str = "",
        region: str = "us-east-1",
        search_type: str = "HYBRID",
        reranking: bool = False,
        rerank_model_arn: str = "",
        rerank_oversample: int = 3,
    ):
        self.kb_id = kb_id
        self.s3_bucket = s3_bucket
        self.s3_prefix = s3_prefix.rstrip("/") + "/"
        self.data_source_id = data_source_id
        self.region = region
        self.search_type = search_type.upper()
        self.reranking = reranking
        self.rerank_model_arn = rerank_model_arn or _DEFAULT_RERANK_MODEL.format(region=region)
        self.rerank_oversample = max(1, rerank_oversample)
        self._session = aioboto3.Session()

    def _build_reranking_config(self, n_results: int) -> dict[str, Any]:
        """Build the rerankingConfiguration block for the retrieve call."""
        return {
            "type": "BEDROCK_RERANKING_MODEL",
            "bedrockRerankingConfiguration": {
                "modelConfiguration": {
                    "modelArn": self.rerank_model_arn,
                },
                "numberOfRerankedResults": n_results,
            },
        }

    async def search(self, query: str, tags: Set[str], n_results: int = 5) -> list[Chunk]:
        # When reranking, over-fetch so the cross-encoder has more candidates.
        fetch_n = n_results * self.rerank_oversample if self.reranking else n_results

        call_kwargs: dict[str, Any] = {
            "knowledgeBaseId": self.kb_id,
            "retrievalQuery": {"text": query},
            "retrievalConfiguration": build_vector_search_config(tags, fetch_n, self.search_type),
        }

        if self.reranking:
            call_kwargs["rerankingConfiguration"] = self._build_reranking_config(n_results)

        async with self._session.client("bedrock-agent-runtime", region_name=self.region) as client:
            response = await client.retrieve(**call_kwargs)

        results: list[Chunk] = []
        for item in response.get("retrievalResults", []):
            content = item.get("content", {}).get("text", "")
            score = item.get("score", 0.0)
            location = item.get("location", {})
            metadata: dict[str, Any] = dict(item.get("metadata", {}))
            metadata["source"] = location.get("s3Location", {}).get("uri", "")
            results.append({"text": content, "metadata": metadata, "score": score})

        return results

    async def ingest(
        self,
        text: str,
        access_tags: list[str],
        doc_id: str,
        metadata: Mapping[str, MetadataValue] | None = None,
    ) -> None:
        s3_key = f"{self.s3_prefix}{validate_doc_id(doc_id)}.txt"
        meta_key = f"{s3_key}.metadata.json"
        # Bedrock KB sidecar format: flat key-value pairs next to the document.
        metadata_doc = {"metadataAttributes": stamp_metadata(access_tags, metadata)}

        async with self._session.client("s3", region_name=self.region) as s3:
            await s3.put_object(Bucket=self.s3_bucket, Key=s3_key, Body=text.encode("utf-8"))
            await s3.put_object(
                Bucket=self.s3_bucket,
                Key=meta_key,
                Body=json.dumps(metadata_doc).encode("utf-8"),
                ContentType="application/json",
            )

        # Trigger KB sync if a data source ID is configured
        if self.data_source_id:
            async with self._session.client("bedrock-agent", region_name=self.region) as client:
                await client.start_ingestion_job(
                    knowledgeBaseId=self.kb_id,
                    dataSourceId=self.data_source_id,
                )
