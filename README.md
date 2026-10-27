# sentinel-engine

[![CI](https://github.com/aashishravindran/sentinel-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/aashishravindran/sentinel-engine/actions/workflows/ci.yml)
[![License: EL2](https://img.shields.io/badge/License-Elastic_2.0-blue.svg)](LICENSE)

**The policy decision point for permission-aware RAG.** Given a verified user, it resolves
which documents they may read right now, turns that into a filter inside your vector query,
re-checks every result, and fails closed.

It is the engine behind [Sentinel](https://github.com/aashishravindran/Sentinel)'s MCP server
and AgentCore Gateway interceptors, and it works on its own in any Python RAG pipeline.

```bash
pip install "sentinel-rag-engine[spicedb]"
```

On PyPI the package is **`sentinel-rag-engine`** (the name `sentinel-engine` there belongs to an
unrelated project); you still `import sentinel_engine`. Pinning the git tag keeps working:
`pip install "sentinel-engine[spicedb] @ git+https://github.com/aashishravindran/sentinel-engine@v0.1.0"`.
See [Moving from the git tag to PyPI](#moving-from-the-git-tag-to-pypi).

```python
from sentinel_engine import SentinelEngine, AccessDeniedError
from sentinel_engine.connectors.identity.spicedb import SpiceDBIdentityConnector
from sentinel_engine.connectors.knowledge.bedrock import BedrockKnowledgeConnector
from sentinel_engine.oidc import OIDCSettings, TokenVerifier

verifier = TokenVerifier(OIDCSettings.from_env())  # any OIDC issuer
engine = SentinelEngine(
    SpiceDBIdentityConnector(endpoint, token), BedrockKnowledgeConnector(kb_id, bucket)
)

user = verifier.verify_authorization_header(request.headers["authorization"])
try:
    chunks = await engine.secure_search("What is the 2026 budget?", user)  # filtered + re-checked
except AccessDeniedError:
    ...  # no tags, identity store down, bad subject: always a denial
```

## What it guarantees

| | |
|---|---|
| **The user is the token's `sub`** | `client_id` and `azp` are never treated as the user. RS256 only; `exp`, `nbf`, issuer, audience and allowed clients are checked. Subjects like `*` (a SpiceDB wildcard) are rejected. |
| **Permissions are live** | Resolved on every call, never cached. Revoking a team membership applies to the next search. |
| **Filters are pushed into the query** | One deterministic builder for Bedrock, Managed KB and Chroma. An empty scope raises instead of matching everything. |
| **Results are re-checked** | A store that ignores the filter still cannot return an unauthorized chunk. |
| **Fail closed** | Empty scope, identity errors and timeouts deny before the knowledge base is called. |
| **Ingest cannot rewrite access** | Tags are stamped after caller metadata; reserved keys, path-like document IDs and invalid tags are rejected. |

## Connectors

| Identity | Extra | | Knowledge | Extra |
|---|---|---|---|---|
| SpiceDB (ReBAC, teams) | `spicedb` | | Bedrock Knowledge Bases (hybrid, rerank) | `aws` |
| DynamoDB | `aws` | | ChromaDB | `chroma` |
| AWS IAM tags | `aws` | | | |
| SQLite | `sqlite` | | | |

Write your own by implementing `IdentityConnector.get_tags` or `KnowledgeConnector.search`
and `ingest`. Use `sentinel_engine.filters` and `sentinel_engine.ingest.stamp` so your
connector filters and stamps exactly like the built-in ones.

## Modules

| Module | |
|---|---|
| `engine` | `SentinelEngine`: `resolve_scope`, `secure_search`, `is_admin` |
| `oidc` | `OIDCSettings`, `TokenVerifier`, `principal_from_claims` |
| `principal` | `Principal`, `validate_subject` |
| `filters` | Filter builders, `chunk_authorized`, `authorize_chunks` |
| `authz` | Admin policies: a SpiceDB relationship or the reserved `sentinel_admin` tag |
| `ingest.stamp` | `stamp_metadata`, `validate_doc_id`, `validate_access_tags` |
| `results` | Relevance threshold and result formatting shared by adapters |
| `telemetry` | Per-layer timings: `with collect_timings() as t: ...` |
| `factory` | `build_engine_from_env()` |

## Development

```bash
uv sync --all-extras
uv run pytest && uv run ruff check . && uv run pyright
```

Licensed under the [Elastic License 2.0](LICENSE).

## Moving from the git tag to PyPI

Versions up to `v0.1.0` are installed from git as `sentinel-engine`; from `0.2.0` they are on PyPI as
`sentinel-rag-engine`. The code and the import name are the same, so switching is one dependency
line. With uv:

```toml
# before
dependencies = ["sentinel-engine[aws]"]
[tool.uv.sources]
sentinel-engine = { git = "https://github.com/aashishravindran/sentinel-engine", tag = "v0.1.0" }

# after
dependencies = ["sentinel-rag-engine[aws]>=0.2,<0.3"]
```

Install one or the other, never both: they provide the same `sentinel_engine` package. Don't drop the
`[tool.uv.sources]` entry while still depending on `sentinel-engine`; plain `sentinel-engine` on PyPI is
someone else's project.

