# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

import json

import aioboto3

from sentinel_engine.base import KnowledgeConnector

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

    Environment variables used by main.py:
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

    def _build_filter(self, tags: set[str]) -> dict:
        """OR filter: return docs where the user holds at least one access tag."""
        conditions = [{"equals": {"key": f"tag_{tag}", "value": True}} for tag in tags]
        if len(conditions) == 1:
            return conditions[0]
        return {"orAll": conditions}

    def _build_retrieval_config(self, tags: set[str], fetch_n: int) -> dict:
        """
        Build the retrievalConfiguration block.

        fetch_n is the number of candidates to retrieve from the KB.
        When reranking is enabled this is n_results * rerank_oversample so the
        reranker has enough candidates to work with.
        """
        vector_search: dict = {
            "numberOfResults": fetch_n,
            "filter": self._build_filter(tags),
            "overrideSearchType": self.search_type,
        }
        return {"vectorSearchConfiguration": vector_search}

    def _build_reranking_config(self, n_results: int) -> dict:
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

    async def search(self, query: str, tags: set[str], n_results: int = 5) -> list[dict]:
        # When reranking, over-fetch so the cross-encoder has more candidates.
        fetch_n = n_results * self.rerank_oversample if self.reranking else n_results

        retrieval_config = self._build_retrieval_config(tags, fetch_n)

        call_kwargs: dict = {
            "knowledgeBaseId": self.kb_id,
            "retrievalQuery": {"text": query},
            "retrievalConfiguration": retrieval_config,
        }

        if self.reranking:
            call_kwargs["rerankingConfiguration"] = self._build_reranking_config(n_results)

        async with aioboto3.Session().client(
            "bedrock-agent-runtime", region_name=self.region
        ) as client:
            response = await client.retrieve(**call_kwargs)

        results = []
        for item in response.get("retrievalResults", []):
            content = item.get("content", {}).get("text", "")
            score = item.get("score", 0.0)
            location = item.get("location", {})
            metadata = dict(item.get("metadata", {}))
            metadata["source"] = location.get("s3Location", {}).get("uri", "")
            results.append({"text": content, "metadata": metadata, "score": score})

        return results

    async def ingest(
        self,
        text: str,
        access_tags: list[str],
        doc_id: str,
        metadata: dict | None = None,
    ) -> None:
        s3_key = f"{self.s3_prefix}{doc_id}.txt"
        meta_key = f"{s3_key}.metadata.json"

        # Bedrock KB metadata format: flat key-value pairs
        attrs: dict = {}
        for tag in access_tags:
            attrs[f"tag_{tag}"] = True
        attrs["access_tags"] = ",".join(access_tags)
        if metadata:
            for k, v in metadata.items():
                attrs[k] = str(v)

        metadata_doc = {"metadataAttributes": attrs}

        async with aioboto3.Session().client("s3", region_name=self.region) as s3:
            await s3.put_object(Bucket=self.s3_bucket, Key=s3_key, Body=text.encode("utf-8"))
            await s3.put_object(
                Bucket=self.s3_bucket,
                Key=meta_key,
                Body=json.dumps(metadata_doc).encode("utf-8"),
                ContentType="application/json",
            )

        # Trigger KB sync if a data source ID is configured
        if self.data_source_id:
            async with aioboto3.Session().client(
                "bedrock-agent", region_name=self.region
            ) as client:
                await client.start_ingestion_job(
                    knowledgeBaseId=self.kb_id,
                    dataSourceId=self.data_source_id,
                )
