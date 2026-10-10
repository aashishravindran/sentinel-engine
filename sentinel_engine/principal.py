# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""The verified caller. Adapters build one from their transport; the model never does."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from sentinel_engine.errors import IdentityError

# Safe as a SpiceDB object ID and a DynamoDB key. Rejects "*" (a SpiceDB
# wildcard subject), whitespace, "@" and ".", so emails are not accepted as-is.
SUBJECT_PATTERN = re.compile(r"[A-Za-z0-9/_|\-=+]{1,128}")

PrincipalSource = Literal["jwt", "stdio", "gateway"]


@dataclass(frozen=True)
class Principal:
    user_id: str
    source: PrincipalSource
    claims: Mapping[str, Any] = field(default_factory=dict[str, Any])


def validate_subject(subject: object) -> str:
    """Return *subject* if it is a usable user ID, else raise IdentityError."""
    if not isinstance(subject, str) or not SUBJECT_PATTERN.fullmatch(subject):
        raise IdentityError("caller identity is missing or malformed")
    return subject
