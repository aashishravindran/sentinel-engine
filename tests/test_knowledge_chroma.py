import pytest


@pytest.mark.asyncio
async def test_ingest_and_retrieve(knowledge):
    results = await knowledge.search("company overview", {"public"})
    assert any("overview" in r["text"].lower() for r in results)


@pytest.mark.asyncio
async def test_or_policy_single_tag_sees_multi_tag_doc(knowledge):
    """A doc tagged [finance, engineering] should be visible to a user with just engineering."""
    results = await knowledge.search("roadmap series D AI pod", {"engineering"})
    doc_ids = [r["metadata"]["title"] for r in results]
    assert "internal_roadmap" in doc_ids


@pytest.mark.asyncio
async def test_tag_filter_blocks_unauthorized_docs(knowledge):
    """A public-only user must not receive finance documents."""
    results = await knowledge.search("budget opex", {"public"})
    for r in results:
        access_tags = set(r["metadata"]["access_tags"].split(","))
        assert "public" in access_tags, (
            f"Returned doc '{r['metadata']['title']}' is not accessible to a public-only user"
        )


@pytest.mark.asyncio
async def test_search_returns_scores(knowledge):
    results = await knowledge.search("on-call grafana", {"engineering"})
    assert results
    for r in results:
        assert "score" in r
        assert 0.0 <= r["score"] <= 1.0


@pytest.mark.asyncio
async def test_upsert_replaces_existing_doc(knowledge):
    """Ingesting a doc with the same ID should overwrite it."""
    await knowledge.ingest(
        "Updated text v2.", ["public"], "public_overview", {"title": "public_overview"}
    )
    results = await knowledge.search("Updated text v2", {"public"})
    assert any("Updated text v2" in r["text"] for r in results)
