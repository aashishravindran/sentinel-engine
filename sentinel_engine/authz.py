# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Who may run admin operations (ingest, config, auditing other users).

Admin checks fail closed: any error answers "not an admin".
"""

from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from sentinel_engine.base import IdentityConnector
from sentinel_engine.filters import ADMIN_TAG


@runtime_checkable
class PermissionChecker(Protocol):
    async def check_permission(
        self, resource_type: str, resource_id: str, permission: str, user_id: str
    ) -> bool: ...


class AdminPolicy(ABC):
    @abstractmethod
    async def is_admin(self, user_id: str) -> bool: ...


class TagAdminPolicy(AdminPolicy):
    """Admin if the identity store gives the user the reserved ``sentinel_admin`` tag."""

    def __init__(self, identity: IdentityConnector):
        self.identity = identity

    async def is_admin(self, user_id: str) -> bool:
        try:
            return ADMIN_TAG in await self.identity.get_tags(user_id)
        except Exception:
            return False


class RelationshipAdminPolicy(AdminPolicy):
    """Admin if the store grants ``administer`` on ``platform:sentinel`` (SpiceDB)."""

    def __init__(self, checker: PermissionChecker):
        self.checker = checker

    async def is_admin(self, user_id: str) -> bool:
        try:
            return await self.checker.check_permission(
                "platform", "sentinel", "administer", user_id
            )
        except Exception:
            return False


def default_admin_policy(identity: IdentityConnector) -> AdminPolicy:
    if isinstance(identity, PermissionChecker):
        return RelationshipAdminPolicy(identity)
    return TagAdminPolicy(identity)
