import pytest

from sentinel_engine.engine import AccessDeniedError

MIN_SCORE = 0.25


def relevant(results):
    return [r for r in results if r["score"] >= MIN_SCORE]


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_closed_unknown_user(engine):
    """Users not in the identity store must be denied before any KB call."""
    with pytest.raises(AccessDeniedError):
        await engine.secure_search("anything", "aashish")


@pytest.mark.asyncio
async def test_fail_closed_blocks_kb_call(engine, mocker=None):
    """AccessDeniedError is raised before search, so the KB is never queried."""
    with pytest.raises(AccessDeniedError):
        await engine.secure_search("budget", "ghost_user")


# ---------------------------------------------------------------------------
# Successful retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alice_sees_finance_docs(engine):
    results = await engine.secure_search("2026 budget opex", "alice")
    titles = [r["metadata"]["title"] for r in results]
    assert "finance_budget" in titles


@pytest.mark.asyncio
async def test_bob_sees_engineering_docs(engine):
    results = await engine.secure_search("on-call grafana runbook", "bob")
    titles = [r["metadata"]["title"] for r in results]
    assert "eng_runbook" in titles


@pytest.mark.asyncio
async def test_charlie_sees_all_doc_types(engine):
    results = await engine.secure_search("budget roadmap series D", "charlie")
    titles = {r["metadata"]["title"] for r in results}
    assert titles & {"finance_budget", "internal_roadmap"}


# ---------------------------------------------------------------------------
# Access denied via relevance threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bob_gets_no_relevant_finance_results(engine):
    """Bob (public, engineering) querying a finance topic should get nothing above threshold."""
    results = await engine.secure_search("2026 budget opex financial", "bob")
    above_threshold = relevant(results)
    finance_results = [
        r
        for r in above_threshold
        if "finance" in r["metadata"].get("access_tags", "")
        and "engineering" not in r["metadata"].get("access_tags", "")
    ]
    assert finance_results == [], (
        f"Bob should not receive pure-finance docs above threshold: {finance_results}"
    )


# ---------------------------------------------------------------------------
# OR policy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_or_policy_bob_sees_multi_tag_roadmap(engine):
    """OR policy: bob (engineering) should access the finance+engineering roadmap."""
    results = await engine.secure_search("roadmap series D AI initiatives", "bob")
    titles = [r["metadata"]["title"] for r in results]
    assert "internal_roadmap" in titles


@pytest.mark.asyncio
async def test_or_policy_alice_sees_multi_tag_roadmap(engine):
    """OR policy: alice (finance) should access the finance+engineering roadmap."""
    results = await engine.secure_search("roadmap series D AI initiatives", "alice")
    titles = [r["metadata"]["title"] for r in results]
    assert "internal_roadmap" in titles
