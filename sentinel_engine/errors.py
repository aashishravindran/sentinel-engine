# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Exceptions shared by the engine and its adapters."""


class AccessDeniedError(Exception):
    """The caller may not proceed. Adapters turn this into a generic denial."""


class IdentityError(AccessDeniedError):
    """The caller's identity is missing, malformed or could not be verified."""


class ConfigError(ValueError):
    """Sentinel is misconfigured and refuses to start rather than run open."""
