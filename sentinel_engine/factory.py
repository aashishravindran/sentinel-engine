# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Build a SentinelEngine from environment variables.

Backends are imported lazily so a deployment only needs the extras it uses.
"""

import os
from collections.abc import Mapping

from sentinel_engine.base import IdentityConnector, KnowledgeConnector
from sentinel_engine.engine import SentinelEngine
from sentinel_engine.errors import ConfigError


def _region(env: Mapping[str, str]) -> str:
    return env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-east-1"


def build_identity_from_env(env: Mapping[str, str] = os.environ) -> IdentityConnector:
    store = env.get("SENTINEL_IDENTITY_STORE", "")
    if store == "sqlite":
        from sentinel_engine.connectors.identity.sqlite import SQLiteIdentityConnector

        return SQLiteIdentityConnector(env.get("SQLITE_DB_PATH", "./data/permissions.db"))
    if store == "dynamodb":
        from sentinel_engine.connectors.identity.ddb import DynamoDBIdentityConnector

        return DynamoDBIdentityConnector(env["DDB_TABLE_NAME"], _region(env))
    if store == "spicedb":
        from sentinel_engine.connectors.identity.spicedb import SpiceDBIdentityConnector

        return SpiceDBIdentityConnector(
            env["SPICEDB_ENDPOINT"],
            env["SPICEDB_TOKEN"],
            tls=env.get("SPICEDB_TLS", "true").lower() == "true",
            resource_type=env.get("SPICEDB_RESOURCE_TYPE", "tag"),
            permission=env.get("SPICEDB_PERMISSION", "access"),
            user_type=env.get("SPICEDB_USER_TYPE", "user"),
            timeout_seconds=float(env.get("SPICEDB_TIMEOUT_S", "2")),
        )
    if store == "iam":
        from sentinel_engine.connectors.identity.iam import IAMIdentityConnector

        return IAMIdentityConnector(
            _region(env),
            principal_type=env.get("IAM_PRINCIPAL_TYPE", "user"),
            tag_format=env.get("IAM_TAG_FORMAT", "key:value"),
            tag_key_prefix=env.get("IAM_TAG_KEY_PREFIX", ""),
        )
    raise ConfigError(f"unsupported SENTINEL_IDENTITY_STORE: {store!r}")


def build_knowledge_from_env(env: Mapping[str, str] = os.environ) -> KnowledgeConnector:
    store = env.get("SENTINEL_KNOWLEDGE_STORE", "")
    if store == "chroma":
        from sentinel_engine.connectors.knowledge.chroma import ChromaKnowledgeConnector

        return ChromaKnowledgeConnector(
            env.get("CHROMA_PATH", "./data/chroma"),
            env.get("CHROMA_COLLECTION", "sentinel"),
            env.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
        )
    if store == "bedrock":
        from sentinel_engine.connectors.knowledge.bedrock import BedrockKnowledgeConnector

        return BedrockKnowledgeConnector(
            env["BEDROCK_KB_ID"],
            env.get("BEDROCK_S3_BUCKET", ""),
            env.get("BEDROCK_S3_PREFIX", "documents/"),
            env.get("BEDROCK_DS_ID", ""),
            _region(env),
            search_type=env.get("BEDROCK_SEARCH_TYPE", "HYBRID"),
            reranking=env.get("BEDROCK_RERANKING", "false").lower() == "true",
            rerank_model_arn=env.get("BEDROCK_RERANK_MODEL_ARN", ""),
            rerank_oversample=int(env.get("BEDROCK_RERANK_OVERSAMPLE", "3")),
        )
    raise ConfigError(f"unsupported SENTINEL_KNOWLEDGE_STORE: {store!r}")


def build_engine_from_env(env: Mapping[str, str] = os.environ) -> SentinelEngine:
    return SentinelEngine(build_identity_from_env(env), build_knowledge_from_env(env))
