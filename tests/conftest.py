import aiosqlite
import pytest_asyncio

from sentinel_engine.connectors.identity.sqlite import SQLiteIdentityConnector
from sentinel_engine.connectors.knowledge.chroma import ChromaKnowledgeConnector
from sentinel_engine.engine import SentinelEngine

# ---------------------------------------------------------------------------
# Shared embedding model — loaded once per session to keep tests fast
# ---------------------------------------------------------------------------
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


# ---------------------------------------------------------------------------
# Identity store fixtures
# ---------------------------------------------------------------------------

SEED_PERMISSIONS = [
    ("alice", "finance"),
    ("alice", "public"),
    ("bob", "public"),
    ("bob", "engineering"),
    ("charlie", "finance"),
    ("charlie", "engineering"),
    ("charlie", "public"),
]


@pytest_asyncio.fixture
async def sqlite_db(tmp_path):
    """Temporary SQLite DB seeded with test users."""
    db_path = str(tmp_path / "permissions.db")
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "CREATE TABLE permissions ("
            "user_id TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (user_id, tag))"
        )
        await db.executemany("INSERT INTO permissions VALUES (?, ?)", SEED_PERMISSIONS)
        await db.commit()
    return db_path


@pytest_asyncio.fixture
async def identity(sqlite_db):
    return SQLiteIdentityConnector(sqlite_db)


# ---------------------------------------------------------------------------
# Knowledge store fixtures
# ---------------------------------------------------------------------------

SEED_DOCS = [
    ("public_overview", "Company overview open to all staff.", ["public"]),
    ("finance_budget", "2026 budget: $88.9M total opex planned.", ["finance"]),
    ("eng_runbook", "On-call runbook: check Grafana first.", ["engineering"]),
    ("internal_roadmap", "Roadmap: Series D in Q3, AI pod in Q1.", ["finance", "engineering"]),
]


@pytest_asyncio.fixture
async def knowledge(tmp_path):
    """Temporary ChromaDB seeded with test documents."""
    chroma_path = str(tmp_path / "chroma")
    connector = ChromaKnowledgeConnector(chroma_path, "test", EMBEDDING_MODEL)
    for doc_id, text, tags in SEED_DOCS:
        await connector.ingest(text, tags, doc_id, {"title": doc_id})
    return connector


@pytest_asyncio.fixture
async def engine(identity, knowledge):
    return SentinelEngine(identity, knowledge)
