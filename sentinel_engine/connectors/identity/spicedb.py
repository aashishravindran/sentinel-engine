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

Configuration env vars (used by main.py):
    SPICEDB_ENDPOINT        gRPC target, e.g. ``localhost:50051``
    SPICEDB_TOKEN           Pre-shared key / bearer token
    SPICEDB_TLS             ``true`` (default) or ``false``
    SPICEDB_RESOURCE_TYPE   SpiceDB object type for tags (default: ``tag``)
    SPICEDB_PERMISSION      Permission to check (default: ``access``)
    SPICEDB_USER_TYPE       SpiceDB subject type for users (default: ``user``)
"""

from __future__ import annotations

import grpc
import grpc.aio
from authzed.api.v1 import (
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
    ) -> None:
        self.endpoint = endpoint
        self.token = token
        self.tls = tls
        self.resource_type = resource_type
        self.permission = permission
        self.user_type = user_type

    def _make_stub(self) -> tuple[PermissionsServiceStub, list[tuple[str, str]]]:
        """Create a gRPC stub and the per-call metadata needed for auth.

        For TLS connections the token is embedded in composite channel
        credentials; for insecure connections it is sent as per-call metadata.
        Returns ``(stub, metadata)`` where *metadata* may be empty.
        """
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

        return PermissionsServiceStub(channel), metadata

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
        async for resource in stub.LookupResources(request, metadata=metadata):
            tags.add(resource.resource_object_id)
        return tags

    async def read_relationships(self, user_id: str) -> list[dict]:
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
        rels: list[dict] = []
        async for resp in stub.ReadRelationships(request, metadata=metadata):
            rel = resp.relationship
            rels.append(
                {
                    "resource_type": rel.resource.object_type,
                    "resource_id": rel.resource.object_id,
                    "relation": rel.relation,
                }
            )
        return rels
