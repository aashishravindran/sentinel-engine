"""Engine-level policy: scope resolution, fail-closed behavior and admin checks.

Uses in-memory fakes so each rule is tested without a vector store.
"""

import pytest

from sentinel_engine import AccessDeniedError, IdentityConnector, KnowledgeConnector
from sentinel_engine.authz import RelationshipAdminPolicy, TagAdminPolicy, default_admin_policy
from sentinel_engine.engine import SentinelEngine
from sentinel_engine.errors import IdentityError
from sentinel_engine.principal import Principal
from sentinel_engine.telemetry import collect_timings


class DictIdentity(IdentityConnector):
    def __init__(self, tags: dict[str, set[str]], fail: bool = False):
        self.tags = tags
        self.fail = fail
        self.calls: list[str] = []

    async def get_tags(self, user_id):
        self.calls.append(user_id)
        if self.fail:
            raise ConnectionError("identity store down")
        return set(self.tags.get(user_id, set()))


class RecordingKB(KnowledgeConnector):
    """Returns every stored chunk regardless of tags, to prove the post-filter works."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.calls = 0

    async def search(self, query, tags, n_results=5):
        self.calls += 1
        return list(self.chunks)

    async def ingest(self, text, access_tags, doc_id, metadata=None):
        raise NotImplementedError


CHUNKS = [
    {"text": "handbook", "metadata": {"access_tags": "public"}, "score": 0.9},
    {"text": "budget", "metadata": {"access_tags": "finance"}, "score": 0.9},
    {"text": "orphan", "metadata": {}, "score": 0.9},
]


@pytest.fixture
def identity():
    return DictIdentity(
        {
            "alice": {"finance", "public"},
            "intern": {"public"},
            "admin": {"sentinel_admin"},
            "odd": {"public", "bad tag", ""},
        }
    )


@pytest.fixture
def kb():
    return RecordingKB(CHUNKS)


async def test_leaky_store_cannot_leak_through_the_engine(identity, kb):
    engine = SentinelEngine(identity, kb)
    results = await engine.secure_search("anything", "intern")
    assert [r["text"] for r in results] == ["handbook"]


async def test_principal_and_string_ids_resolve_the_same(identity, kb):
    engine = SentinelEngine(identity, kb)
    by_principal = await engine.secure_search("q", Principal("alice", "jwt"))
    by_string = await engine.secure_search("q", "alice")
    assert by_principal == by_string


async def test_identity_outage_denies_without_touching_the_kb(kb):
    engine = SentinelEngine(DictIdentity({}, fail=True), kb)
    with pytest.raises(AccessDeniedError):
        await engine.secure_search("q", "alice")
    assert kb.calls == 0


async def test_admin_tag_grants_no_document_access(identity, kb):
    engine = SentinelEngine(identity, kb)
    with pytest.raises(AccessDeniedError):
        await engine.secure_search("q", "admin")
    assert kb.calls == 0


async def test_malformed_tags_from_the_store_are_dropped(identity, kb):
    engine = SentinelEngine(identity, kb)
    assert await engine.resolve_scope("odd") == {"public"}


@pytest.mark.parametrize("user_id", ["*", "", "alice@example.com", "a b"])
async def test_malformed_user_ids_never_reach_the_store(identity, kb, user_id):
    engine = SentinelEngine(identity, kb)
    with pytest.raises(IdentityError):
        await engine.secure_search("q", user_id)
    assert identity.calls == []


async def test_scope_is_resolved_live_every_call(identity, kb):
    engine = SentinelEngine(identity, kb)
    assert [r["text"] for r in await engine.secure_search("q", "alice")] == ["handbook", "budget"]
    identity.tags["alice"] = {"public"}
    assert [r["text"] for r in await engine.secure_search("q", "alice")] == ["handbook"]


async def test_tag_admin_policy(identity, kb):
    engine = SentinelEngine(identity, kb)
    assert isinstance(engine.admin_policy, TagAdminPolicy)
    assert await engine.is_admin("admin")
    assert not await engine.is_admin("alice")


async def test_admin_check_fails_closed():
    assert not await TagAdminPolicy(DictIdentity({}, fail=True)).is_admin("admin")


class Checker(DictIdentity):
    def __init__(self, admins: set[str], fail: bool = False):
        super().__init__({})
        self.admins = admins
        self.fail_checks = fail

    async def check_permission(self, resource_type, resource_id, permission, user_id):
        if self.fail_checks:
            raise TimeoutError
        return (resource_type, resource_id, permission) == (
            "platform",
            "sentinel",
            "administer",
        ) and user_id in self.admins


async def test_relationship_admin_policy_is_used_when_available():
    checker = Checker({"root"})
    policy = default_admin_policy(checker)
    assert isinstance(policy, RelationshipAdminPolicy)
    assert await policy.is_admin("root")
    assert not await policy.is_admin("alice")
    assert not await RelationshipAdminPolicy(Checker({"root"}, fail=True)).is_admin("root")


async def test_timings_are_collected_per_layer(identity, kb):
    engine = SentinelEngine(identity, kb)
    with collect_timings() as timings:
        await engine.secure_search("q", "alice")
    assert set(timings) == {"identity", "kb", "postfilter"}
