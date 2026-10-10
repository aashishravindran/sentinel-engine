# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""AWS IAM identity connector.

Retrieves a user's permission tags via IAM user or role tags and maps
them to Sentinel permission tags.  The ``tag_format`` parameter controls
what part of each AWS tag becomes the Sentinel tag string:

    ``"key:value"`` (default)  ``Project:Omega``, ``AccessLevel:4``
    ``"key"``                  ``Project``, ``AccessLevel``
    ``"value"``                ``Omega``, ``4``

An optional ``tag_key_prefix`` filters which AWS tags are promoted and
strips the prefix from the key portion before formatting.  For example,
with prefix ``Sentinel/``, only tags whose key starts with ``Sentinel/``
are included: ``Sentinel/Project`` → key portion becomes ``Project``.

Configuration env vars (used by main.py):
    AWS_REGION / AWS_DEFAULT_REGION  AWS region (default: ``us-east-1``)
    IAM_PRINCIPAL_TYPE               ``user`` (default) or ``role``
    IAM_TAG_FORMAT                   ``key:value`` (default), ``key``, or ``value``
    IAM_TAG_KEY_PREFIX               Include only tags whose key starts
                                     with this string; strip the prefix
                                     from the key before formatting.
"""

from __future__ import annotations

import aioboto3
from botocore.exceptions import ClientError

from sentinel_engine.base import IdentityConnector


class IAMIdentityConnector(IdentityConnector):
    """Identity connector backed by AWS IAM tags.

    Args:
        region_name:     AWS region for the IAM API (default ``us-east-1``).
        principal_type:  ``"user"`` (default) to call ``list_user_tags``,
                         ``"role"`` to call ``list_role_tags``.
        tag_format:      Controls what part of each AWS tag becomes the
                         Sentinel tag string.  One of:

                         * ``"key:value"`` (default) — ``Project:Omega``
                         * ``"key"``                 — ``Project``
                         * ``"value"``               — ``Omega``

        tag_key_prefix:  If non-empty, only AWS tags whose key starts with
                         this prefix are included, and the prefix is stripped
                         from the key before formatting.
    """

    _VALID_FORMATS = frozenset({"key:value", "key", "value"})

    def __init__(
        self,
        region_name: str = "us-east-1",
        *,
        principal_type: str = "user",
        tag_format: str = "key:value",
        tag_key_prefix: str = "",
    ) -> None:
        if tag_format not in self._VALID_FORMATS:
            raise ValueError(
                f"tag_format must be one of {sorted(self._VALID_FORMATS)}, got '{tag_format}'"
            )
        self.region_name = region_name
        self.principal_type = principal_type
        self.tag_format = tag_format
        self.tag_key_prefix = tag_key_prefix
        self._session = aioboto3.Session()

    def _to_sentinel_tags(self, aws_tags: list[dict]) -> set[str]:
        """Convert a list of AWS tag dicts to Sentinel permission tag strings."""
        tags: set[str] = set()
        for tag in aws_tags:
            key: str = tag["Key"]
            if self.tag_key_prefix and not key.startswith(self.tag_key_prefix):
                continue
            sentinel_key = key[len(self.tag_key_prefix) :] if self.tag_key_prefix else key
            if self.tag_format == "key":
                tags.add(sentinel_key)
            elif self.tag_format == "value":
                tags.add(tag["Value"])
            else:  # key:value
                tags.add(f"{sentinel_key}:{tag['Value']}")
        return tags

    async def get_tags(self, user_id: str) -> set[str]:
        """Return Sentinel permission tags derived from IAM tags for *user_id*.

        Calls ``list_user_tags`` or ``list_role_tags`` depending on
        ``principal_type``.  Returns an empty set (fail-closed) if the
        principal does not exist or any AWS error occurs.
        """
        try:
            async with self._session.client("iam", region_name=self.region_name) as iam:
                if self.principal_type == "role":
                    response = await iam.list_role_tags(RoleName=user_id)
                else:
                    response = await iam.list_user_tags(UserName=user_id)
                return self._to_sentinel_tags(response.get("Tags", []))
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "NoSuchEntity":
                return set()
            print(f"IAMIdentityConnector AWS error [{code}]: {e}")
            return set()
        except Exception as e:
            print(f"IAMIdentityConnector error: {e}")
            return set()
