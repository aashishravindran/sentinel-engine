# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""SpiceDB identity connector.

Retrieves a user's permission tags via SpiceDB's LookupResources RPC.

Expected schema (minimal example)::

    definition user {}

    definition tag {
        relation member: user
        permission access = member
    }

Each tag the user can access appears as a ``tag`` resource where they hold
the ``access`` permission.  ``get_tags("alice")`` performs a LookupResources
call — "which ``tag`` objects does ``user:alice`` have ``access`` on?" — and
returns the matching object IDs as a ``set[str]``.

Configuration env vars (read by sentinel_engine.factory):
    SPICEDB_ENDPOINT        gRPC target, e.g. ``localhost:50051``
    SPICEDB_TOKEN           Pre-shared key / bearer token
    SPICEDB_TLS             ``true`` (default) or ``false``
    SPICEDB_RESOURCE_TYPE   SpiceDB object type for tags (default: ``tag``)
    SPICEDB_PERMISSION      Permission to check (default: ``access``)
    SPICEDB_USER_TYPE       SpiceDB subject type for users (default: ``user``)
    SPICEDB_TIMEOUT_S       Deadline for every RPC in seconds (default: ``2``)
"""

from __future__ import annotations

import asyncio
from typing import Any

import grpc
import grpc.aio
from authzed.api.v1 import (
    CheckPermissionRequest,
    CheckPermissionResponse,
    LookupResourcesRequest,
    ObjectReference,
    ReadRelationshipsRequest,
    RelationshipFilter,
    SubjectFilter,
    SubjectReference,
)
from authzed.api.v1.permission_service_pb2_grpc import PermissionsServiceStub

from sentinel_engine.base import IdentityConnector


class SpiceDBIdentityConnector(IdentityConnector):
    """Identity connector backed by SpiceDB.

    Uses ``LookupResources`` to find every tag resource the user can access.

    Args:
        endpoint: gRPC target (e.g. ``localhost:50051`` or ``grpc.example.com:443``).
        token: Bearer token (pre-shared key) for the SpiceDB API.
        tls: Use TLS. Set ``False`` for a local/dev SpiceDB with no certificate.
        resource_type: SpiceDB object type representing a tag (default ``tag``).
        permission: Permission name to look up (default ``access``).
        user_type: SpiceDB object type for users (default ``user``).
        timeout_seconds: Deadline for every RPC. A slow SpiceDB denies, it never hangs.
    """

    def __init__(
        self,
        endpoint: str,
        token: str,
        *,
        tls: bool = True,
        resource_type: str = "tag",
        permission: str = "access",
        user_type: str = "user",
        timeout_seconds: float = 2.0,
    ) -> None:
        self.endpoint = endpoint
        self.token = token
        self.tls = tls
        self.resource_type = resource_type
        self.permission = permission
        self.user_type = user_type
        self.timeout_seconds = timeout_seconds
        self._channel: grpc.aio.Channel | None = None
        self._connection: tuple[Any, list[tuple[str, str]]] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def _make_stub(self) -> tuple[Any, list[tuple[str, str]]]:
        """Return a gRPC stub and the per-call metadata needed for auth.

        One channel is reused per event loop (gRPC aio channels are bound to the
        loop that created them), so warm processes do not leak connections.
        For TLS the token travels in channel credentials; otherwise as metadata.
        """
        loop = asyncio.get_running_loop()
        if self._connection is not None and self._loop is loop:
            return self._connection
        if self.tls:
            channel_creds = grpc.composite_channel_credentials(
                grpc.ssl_channel_credentials(),
                grpc.access_token_call_credentials(self.token),
            )
            channel = grpc.aio.secure_channel(self.endpoint, channel_creds)
            metadata: list[tuple[str, str]] = []
        else:
            channel = grpc.aio.insecure_channel(self.endpoint)
            metadata = [("authorization", f"Bearer {self.token}")]

        self._channel, self._loop = channel, loop
        self._connection = (PermissionsServiceStub(channel), metadata)
        return self._connection

    async def aclose(self) -> None:
        if self._channel is not None:
            await self._channel.close()
        self._channel = self._connection = self._loop = None

    async def get_tags(self, user_id: str) -> set[str]:
        """Return the set of tag IDs accessible to *user_id* in SpiceDB.

        Performs a ``LookupResources`` streaming call and collects every
        ``resource_object_id`` from the response.  Returns an empty set if
        the user has no matching relationships (the engine enforces
        fail-closed policy on empty sets).
        """
        stub, metadata = self._make_stub()
        request = LookupResourcesRequest(
            resource_object_type=self.resource_type,
            permission=self.permission,
            subject=SubjectReference(
                object=ObjectReference(
                    object_type=self.user_type,
                    object_id=user_id,
                )
            ),
        )
        tags: set[str] = set()
        async for resource in stub.LookupResources(
            request, metadata=metadata, timeout=self.timeout_seconds
        ):
            tags.add(resource.resource_object_id)
        return tags

    async def check_permission(
        self, resource_type: str, resource_id: str, permission: str, user_id: str
    ) -> bool:
        """Whether *user_id* has *permission* on ``resource_type:resource_id``."""
        stub, metadata = self._make_stub()
        request = CheckPermissionRequest(
            resource=ObjectReference(object_type=resource_type, object_id=resource_id),
            permission=permission,
            subject=SubjectReference(
                object=ObjectReference(object_type=self.user_type, object_id=user_id)
            ),
        )
        response = await stub.CheckPermission(
            request, metadata=metadata, timeout=self.timeout_seconds
        )
        return response.permissionship == CheckPermissionResponse.PERMISSIONSHIP_HAS_PERMISSION

    async def read_relationships(self, user_id: str) -> list[dict[str, str]]:
        """Return every relationship tuple that *user_id* appears in as a subject.

        Uses ``ReadRelationships`` filtered by subject so it works even when
        ``LookupResources`` can't resolve a permission (e.g. direct relation
        inspection, debugging).  Returns a list of dicts::

            [{"resource_type": "tag", "resource_id": "finance", "relation": "member"}, ...]
        """
        stub, metadata = self._make_stub()
        request = ReadRelationshipsRequest(
            relationship_filter=RelationshipFilter(
                resource_type=self.resource_type,
                optional_subject_filter=SubjectFilter(
                    subject_type=self.user_type,
                    optional_subject_id=user_id,
                ),
            ),
        )
        rels: list[dict[str, str]] = []
        async for resp in stub.ReadRelationships(
            request, metadata=metadata, timeout=self.timeout_seconds
        ):
            rel = resp.relationship
            rels.append(
                {
                    "resource_type": rel.resource.object_type,
                    "resource_id": rel.resource.object_id,
                    "relation": rel.relation,
                }
            )
        return rels
