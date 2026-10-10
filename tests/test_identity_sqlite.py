import pytest


@pytest.mark.asyncio
async def test_known_user_returns_correct_tags(identity):
    tags = await identity.get_tags("alice")
    assert tags == {"finance", "public"}


@pytest.mark.asyncio
async def test_another_known_user(identity):
    tags = await identity.get_tags("bob")
    assert tags == {"public", "engineering"}


@pytest.mark.asyncio
async def test_unknown_user_returns_empty_set(identity):
    tags = await identity.get_tags("aashish")
    assert tags == set()


@pytest.mark.asyncio
async def test_full_access_user(identity):
    tags = await identity.get_tags("charlie")
    assert tags == {"finance", "engineering", "public"}
