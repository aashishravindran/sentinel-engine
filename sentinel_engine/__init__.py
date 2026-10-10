# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Sentinel Engine: the policy decision point behind Sentinel."""

from sentinel_engine.base import IdentityConnector, KnowledgeConnector
from sentinel_engine.engine import AccessDeniedError, SentinelEngine

__all__ = [
    "AccessDeniedError",
    "IdentityConnector",
    "KnowledgeConnector",
    "SentinelEngine",
]
