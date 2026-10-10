# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Unit tests for IAMIdentityConnector.

The aioboto3 layer is mocked so no AWS credentials or live IAM calls
are required.  Each test patches the async context manager returned by
``session.client()`` to inject a fake IAM client.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from sentinel_engine.connectors.identity.iam import IAMIdentityConnector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _client_returning(tags: list[dict]) -> tuple[MagicMock, MagicMock]:
    """Return (mock_cm, mock_iam_client) that yields *tags* from list_user_tags."""
    mock_iam = AsyncMock()
    mock_iam.list_user_tags.return_value = {"Tags": tags}
    mock_iam.list_role_tags.return_value = {"Tags": tags}

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_iam)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm, mock_iam


def _client_raising(code: str) -> MagicMock:
    """Return a mock context manager whose IAM calls raise a ClientError."""
    error_response = {"Error": {"Code": code, "Message": "test error"}}

    mock_iam = AsyncMock()
    mock_iam.list_user_tags.side_effect = ClientError(error_response, "ListUserTags")
    mock_iam.list_role_tags.side_effect = ClientError(error_response, "ListRoleTags")

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_iam)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    return mock_cm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def connector():
    return IAMIdentityConnector(region_name="us-east-1")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_known_user_returns_correct_tags(connector):
    aws_tags = [{"Key": "Project", "Value": "Omega"}, {"Key": "AccessLevel", "Value": "4"}]
    mock_cm, _ = _client_returning(aws_tags)
    with patch.object(connector._session, "client", return_value=mock_cm):
        tags = await connector.get_tags("alice")
    assert tags == {"Project:Omega", "AccessLevel:4"}


@pytest.mark.asyncio
async def test_user_with_no_tags_returns_empty_set(connector):
    mock_cm, _ = _client_returning([])
    with patch.object(connector._session, "client", return_value=mock_cm):
        tags = await connector.get_tags("bob")
    assert tags == set()


@pytest.mark.asyncio
async def test_nonexistent_user_returns_empty_set(connector):
    mock_cm = _client_raising("NoSuchEntity")
    with patch.object(connector._session, "client", return_value=mock_cm):
        tags = await connector.get_tags("nobody")
    assert tags == set()


@pytest.mark.asyncio
async def test_unexpected_aws_error_fails_closed(connector):
    mock_cm = _client_raising("AccessDenied")
    with patch.object(connector._session, "client", return_value=mock_cm):
        tags = await connector.get_tags("alice")
    assert tags == set()


@pytest.mark.asyncio
async def test_role_principal_type_calls_list_role_tags():
    connector = IAMIdentityConnector(region_name="us-east-1", principal_type="role")
    aws_tags = [{"Key": "Team", "Value": "platform"}]
    mock_cm, mock_iam = _client_returning(aws_tags)
    with patch.object(connector._session, "client", return_value=mock_cm):
        tags = await connector.get_tags("my-role")
    mock_iam.list_role_tags.assert_called_once_with(RoleName="my-role")
    mock_iam.list_user_tags.assert_not_called()
    assert tags == {"Team:platform"}


@pytest.mark.asyncio
async def test_user_principal_type_calls_list_user_tags():
    connector = IAMIdentityConnector(region_name="us-east-1", principal_type="user")
    aws_tags = [{"Key": "Dept", "Value": "finance"}]
    mock_cm, mock_iam = _client_returning(aws_tags)
    with patch.object(connector._session, "client", return_value=mock_cm):
        tags = await connector.get_tags("alice")
    mock_iam.list_user_tags.assert_called_once_with(UserName="alice")
    mock_iam.list_role_tags.assert_not_called()
    assert tags == {"Dept:finance"}


@pytest.mark.asyncio
async def test_tag_key_prefix_filters_and_strips():
    connector = IAMIdentityConnector(region_name="us-east-1", tag_key_prefix="Sentinel/")
    aws_tags = [
        {"Key": "Sentinel/Project", "Value": "Omega"},
        {"Key": "Sentinel/AccessLevel", "Value": "4"},
        {"Key": "CostCenter", "Value": "99"},  # no prefix → excluded
        {"Key": "Name", "Value": "alice"},  # no prefix → excluded
    ]
    mock_cm, _ = _client_returning(aws_tags)
    with patch.object(connector._session, "client", return_value=mock_cm):
        tags = await connector.get_tags("alice")
    assert tags == {"Project:Omega", "AccessLevel:4"}


@pytest.mark.asyncio
async def test_tag_key_prefix_no_matches_returns_empty_set():
    connector = IAMIdentityConnector(region_name="us-east-1", tag_key_prefix="Sentinel/")
    aws_tags = [{"Key": "CostCenter", "Value": "99"}, {"Key": "Name", "Value": "alice"}]
    mock_cm, _ = _client_returning(aws_tags)
    with patch.object(connector._session, "client", return_value=mock_cm):
        tags = await connector.get_tags("alice")
    assert tags == set()


@pytest.mark.asyncio
async def test_tag_format_key_only():
    connector = IAMIdentityConnector(region_name="us-east-1", tag_format="key")
    aws_tags = [{"Key": "Project", "Value": "Omega"}, {"Key": "AccessLevel", "Value": "4"}]
    mock_cm, _ = _client_returning(aws_tags)
    with patch.object(connector._session, "client", return_value=mock_cm):
        tags = await connector.get_tags("alice")
    assert tags == {"Project", "AccessLevel"}


@pytest.mark.asyncio
async def test_tag_format_value_only():
    connector = IAMIdentityConnector(region_name="us-east-1", tag_format="value")
    aws_tags = [{"Key": "Project", "Value": "Omega"}, {"Key": "AccessLevel", "Value": "4"}]
    mock_cm, _ = _client_returning(aws_tags)
    with patch.object(connector._session, "client", return_value=mock_cm):
        tags = await connector.get_tags("alice")
    assert tags == {"Omega", "4"}


@pytest.mark.asyncio
async def test_tag_format_key_value_is_default():
    connector = IAMIdentityConnector(region_name="us-east-1")
    aws_tags = [{"Key": "Project", "Value": "Omega"}]
    mock_cm, _ = _client_returning(aws_tags)
    with patch.object(connector._session, "client", return_value=mock_cm):
        tags = await connector.get_tags("alice")
    assert tags == {"Project:Omega"}


def test_invalid_tag_format_raises():
    with pytest.raises(ValueError, match="tag_format"):
        IAMIdentityConnector(tag_format="both")


@pytest.mark.asyncio
async def test_tag_format_key_with_prefix_strips_prefix():
    connector = IAMIdentityConnector(
        region_name="us-east-1", tag_format="key", tag_key_prefix="Sentinel/"
    )
    aws_tags = [
        {"Key": "Sentinel/Project", "Value": "Omega"},
        {"Key": "CostCenter", "Value": "99"},  # excluded by prefix
    ]
    mock_cm, _ = _client_returning(aws_tags)
    with patch.object(connector._session, "client", return_value=mock_cm):
        tags = await connector.get_tags("alice")
    assert tags == {"Project"}


@pytest.mark.asyncio
async def test_iam_client_created_with_correct_region():
    connector = IAMIdentityConnector(region_name="eu-west-1")
    mock_cm, _ = _client_returning([])
    with patch.object(connector._session, "client", return_value=mock_cm) as mock_client_factory:
        await connector.get_tags("alice")
    mock_client_factory.assert_called_once_with("iam", region_name="eu-west-1")
