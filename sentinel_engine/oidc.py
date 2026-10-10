# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

"""Bearer-token verification against any OIDC issuer (Cognito, Okta, Auth0, Entra ...).

The user is the token's ``sub`` claim and nothing else. ``client_id`` and
``azp`` name the calling application, never the user.
"""

import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import jwt

from sentinel_engine.errors import ConfigError, IdentityError
from sentinel_engine.principal import Principal, PrincipalSource, validate_subject

ENV_PREFIX = "SENTINEL_OIDC_"


def _split(value: str | None) -> tuple[str, ...]:
    return tuple(v.strip() for v in (value or "").split(",") if v.strip())


@dataclass(frozen=True)
class OIDCSettings:
    """Who may issue tokens, for whom, and how to check their signatures.

    Set ``audience`` for issuers that put the API in ``aud`` (Okta, Auth0, Entra),
    or ``allowed_clients`` for Cognito access tokens, which carry ``client_id``
    instead of ``aud``. At least one is required.
    """

    issuer: str
    jwks_uri: str | None = None
    public_key: str | None = None
    audience: tuple[str, ...] = ()
    allowed_clients: tuple[str, ...] = ()
    algorithms: tuple[str, ...] = ("RS256",)
    leeway_seconds: int = 30

    def __post_init__(self) -> None:
        if not self.issuer:
            raise ConfigError("OIDC issuer is required")
        if (self.jwks_uri is None) == (self.public_key is None):
            raise ConfigError("set exactly one of OIDC jwks_uri or public_key")
        if not self.audience and not self.allowed_clients:
            raise ConfigError("set an OIDC audience or allowed clients")
        if any(alg.lower() == "none" or alg.startswith("HS") for alg in self.algorithms):
            raise ConfigError("only asymmetric signing algorithms are allowed")

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> "OIDCSettings":
        """Read ``SENTINEL_OIDC_{ISSUER,JWKS_URI,PUBLIC_KEY,AUDIENCE,ALLOWED_CLIENTS}``."""
        return cls(
            issuer=env.get(f"{ENV_PREFIX}ISSUER", ""),
            jwks_uri=env.get(f"{ENV_PREFIX}JWKS_URI") or None,
            public_key=env.get(f"{ENV_PREFIX}PUBLIC_KEY") or None,
            audience=_split(env.get(f"{ENV_PREFIX}AUDIENCE")),
            allowed_clients=_split(env.get(f"{ENV_PREFIX}ALLOWED_CLIENTS")),
        )


def principal_from_claims(
    claims: Mapping[str, Any], settings: OIDCSettings, source: PrincipalSource = "jwt"
) -> Principal:
    """Checks every verifier must apply after the signature is valid.

    Shared with adapters that delegate signature checks to their framework, so
    the rules on ``sub``, expiry and client are identical everywhere.
    """
    exp = claims.get("exp")
    if not isinstance(exp, int | float) or exp + settings.leeway_seconds < time.time():
        raise IdentityError("token is expired or has no expiry")
    if settings.allowed_clients:
        client = claims.get("client_id") or claims.get("azp")
        if client not in settings.allowed_clients:
            raise IdentityError("token was issued to an unexpected client")
    return Principal(validate_subject(claims.get("sub")), source, dict(claims))


class TokenVerifier:
    """Verifies bearer tokens. Construct once and reuse: JWKS keys are cached."""

    def __init__(self, settings: OIDCSettings):
        self.settings = settings
        self._jwks = (
            jwt.PyJWKClient(settings.jwks_uri, cache_keys=True) if settings.jwks_uri else None
        )

    def _signing_key(self, token: str) -> Any:
        if self._jwks is not None:
            return self._jwks.get_signing_key_from_jwt(token).key
        return self.settings.public_key

    def verify(self, token: str, source: PrincipalSource = "jwt") -> Principal:
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                self._signing_key(token),
                algorithms=list(self.settings.algorithms),
                issuer=self.settings.issuer,
                audience=list(self.settings.audience) or None,
                leeway=self.settings.leeway_seconds,
                options={
                    "require": ["exp", "iat", "iss", "sub"],
                    "verify_aud": bool(self.settings.audience),
                },
            )
        except jwt.PyJWTError as exc:
            raise IdentityError("bearer token is invalid") from exc
        return principal_from_claims(claims, self.settings, source)

    def verify_authorization_header(
        self, header: str | None, source: PrincipalSource = "jwt"
    ) -> Principal:
        scheme, _, token = (header or "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise IdentityError("missing bearer token")
        return self.verify(token.strip(), source)
