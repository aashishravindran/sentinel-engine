# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Unit tests for SpiceDBIdentityConnector.

The gRPC layer is mocked so no running SpiceDB instance is required.
The mock intercepts ``_make_stub`` to return a fake stub whose
``LookupResources`` yields pre-configured response items.
"""

from unittest.mock import MagicMock, patch

import pytest

from sentinel_engine.connectors.identity.spicedb import SpiceDBIdentityConnector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resource(tag: str) -> MagicMock:
    """Fake LookupResourcesResponse item with a resource_object_id."""
    r = MagicMock()
    r.resource_object_id = tag
    return r


async def _async_iter(*items):
    """Yield items as an async iterable — simulates a gRPC streaming response."""
    for item in items:
        yield item


def _stub_returning(*tags: str) -> MagicMock:
    """Return a fake PermissionsServiceStub whose LookupResources streams *tags*."""
    stub = MagicMock()
    stub.LookupResources.return_value = _async_iter(*[_resource(t) for t in tags])
    return stub


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def connector():
    """Connector pointed at a fake local endpoint (TLS off)."""
    return SpiceDBIdentityConnector(
        endpoint="localhost:50051",
        token="testtoken",
        tls=False,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_known_user_returns_correct_tags(connector):
    with patch.object(
        connector, "_make_stub", return_value=(_stub_returning("finance", "public"), [])
    ):
        tags = await connector.get_tags("alice")
    assert tags == {"finance", "public"}


@pytest.mark.asyncio
async def test_unknown_user_returns_empty_set(connector):
    with patch.object(connector, "_make_stub", return_value=(_stub_returning(), [])):
        tags = await connector.get_tags("nobody")
    assert tags == set()


@pytest.mark.asyncio
async def test_single_tag_user(connector):
    with patch.object(connector, "_make_stub", return_value=(_stub_returning("engineering"), [])):
        tags = await connector.get_tags("bob")
    assert tags == {"engineering"}


@pytest.mark.asyncio
async def test_lookup_resources_called_with_correct_request(connector):
    """Verify the gRPC request carries the right field values."""
    stub = _stub_returning()
    with patch.object(connector, "_make_stub", return_value=(stub, [])):
        await connector.get_tags("alice")

    call_args = stub.LookupResources.call_args
    request = call_args[0][0]

    assert request.resource_object_type == "tag"
    assert request.permission == "access"
    assert request.subject.object.object_type == "user"
    assert request.subject.object.object_id == "alice"


@pytest.mark.asyncio
async def test_insecure_connector_sends_bearer_metadata():
    """Insecure connectors must forward the token as per-call metadata."""
    connector = SpiceDBIdentityConnector(
        endpoint="localhost:50051",
        token="secret",
        tls=False,
    )
    stub = _stub_returning("public")
    # Capture what metadata is passed to LookupResources
    with patch.object(
        connector, "_make_stub", return_value=(stub, [("authorization", "Bearer secret")])
    ):
        await connector.get_tags("bob")

    _, kwargs = stub.LookupResources.call_args
    assert ("authorization", "Bearer secret") in kwargs.get("metadata", [])


@pytest.mark.asyncio
async def test_custom_resource_permission_and_user_types():
    """Non-default resource_type / permission / user_type are respected."""
    connector = SpiceDBIdentityConnector(
        endpoint="localhost:50051",
        token="tok",
        tls=False,
        resource_type="document_class",
        permission="view",
        user_type="principal",
    )
    stub = _stub_returning("confidential")
    with patch.object(connector, "_make_stub", return_value=(stub, [])):
        tags = await connector.get_tags("eve")

    assert tags == {"confidential"}

    request = stub.LookupResources.call_args[0][0]
    assert request.resource_object_type == "document_class"
    assert request.permission == "view"
    assert request.subject.object.object_type == "principal"
    assert request.subject.object.object_id == "eve"
