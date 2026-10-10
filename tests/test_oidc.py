import base64
import hashlib
import hmac
import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from sentinel_engine.errors import ConfigError, IdentityError
from sentinel_engine.oidc import OIDCSettings, TokenVerifier

ISSUER = "https://issuer.example.com"
AUDIENCE = "sentinel"


def _keypair() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


PRIVATE, PUBLIC = _keypair()
OTHER_PRIVATE, _ = _keypair()


def _token(key: str = PRIVATE, **overrides) -> str:
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "alice", "iat": now, "exp": now + 300}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm="RS256")


def _hs256_signed_with_public_key() -> str:
    """Key-confusion attack: an HMAC token keyed with the RSA public key."""

    def b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

    now = int(time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "ceo", "iat": now, "exp": now + 300}
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    signing_input = f"{header}.{b64(json.dumps(claims).encode())}"
    signature = hmac.new(PUBLIC.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{b64(signature)}"


@pytest.fixture
def verifier() -> TokenVerifier:
    return TokenVerifier(OIDCSettings(issuer=ISSUER, public_key=PUBLIC, audience=(AUDIENCE,)))


def test_valid_token_yields_sub(verifier):
    principal = verifier.verify(_token())
    assert principal.user_id == "alice"
    assert principal.source == "jwt"


def test_header_parsing(verifier):
    assert verifier.verify_authorization_header(f"Bearer {_token()}").user_id == "alice"
    with pytest.raises(IdentityError):
        verifier.verify_authorization_header(None)
    with pytest.raises(IdentityError):
        verifier.verify_authorization_header(f"Basic {_token()}")


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(lambda: _token(exp=int(time.time()) - 3600), id="expired"),
        pytest.param(lambda: _token(nbf=int(time.time()) + 3600), id="not-yet-valid"),
        pytest.param(lambda: _token(iss="https://evil.example.com"), id="wrong-issuer"),
        pytest.param(lambda: _token(aud="someone-else"), id="wrong-audience"),
        pytest.param(lambda: _token(key=OTHER_PRIVATE), id="foreign-key"),
        pytest.param(lambda: _token(sub=None), id="no-sub"),
        pytest.param(lambda: _token(exp=None), id="no-exp"),
        pytest.param(lambda: _token(sub="*"), id="wildcard-sub"),
        pytest.param(lambda: _token(sub="alice@example.com"), id="email-sub"),
        pytest.param(_hs256_signed_with_public_key, id="hs256-with-public-key"),
        pytest.param(lambda: jwt.encode({"sub": "alice"}, None, algorithm="none"), id="alg-none"),
        pytest.param(lambda: "not.a.jwt", id="garbage"),
    ],
)
def test_bad_tokens_are_rejected(verifier, token):
    with pytest.raises(IdentityError):
        verifier.verify(token())


def test_client_id_is_never_the_user(verifier):
    principal = verifier.verify(_token(client_id="ceo", azp="ceo"))
    assert principal.user_id == "alice"


def test_allowed_clients_for_cognito_access_tokens():
    settings = OIDCSettings(issuer=ISSUER, public_key=PUBLIC, allowed_clients=("app-1",))
    verifier = TokenVerifier(settings)
    assert verifier.verify(_token(aud=None, client_id="app-1")).user_id == "alice"
    with pytest.raises(IdentityError):
        verifier.verify(_token(aud=None, client_id="app-2"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"issuer": "", "public_key": PUBLIC, "audience": ("a",)},
        {"issuer": ISSUER, "audience": ("a",)},
        {"issuer": ISSUER, "public_key": PUBLIC, "jwks_uri": "https://x", "audience": ("a",)},
        {"issuer": ISSUER, "public_key": PUBLIC},
        {"issuer": ISSUER, "public_key": PUBLIC, "audience": ("a",), "algorithms": ("HS256",)},
    ],
)
def test_incomplete_settings_refuse_to_start(kwargs):
    with pytest.raises(ConfigError):
        OIDCSettings(**kwargs)


def test_settings_from_env():
    settings = OIDCSettings.from_env(
        {
            "SENTINEL_OIDC_ISSUER": ISSUER,
            "SENTINEL_OIDC_JWKS_URI": "https://issuer.example.com/.well-known/jwks.json",
            "SENTINEL_OIDC_ALLOWED_CLIENTS": "a, b",
        }
    )
    assert settings.allowed_clients == ("a", "b")
    assert settings.audience == ()


def test_claim_checks_reject_not_yet_valid_tokens_even_after_signature_checks():
    """Frameworks that verify signatures (e.g. FastMCP) may skip nbf; Sentinel does not."""
    from sentinel_engine.oidc import principal_from_claims

    settings = OIDCSettings(issuer=ISSUER, public_key=PUBLIC, audience=(AUDIENCE,))
    now = int(time.time())
    with pytest.raises(IdentityError):
        principal_from_claims({"sub": "alice", "exp": now + 300, "nbf": now + 3600}, settings)
    assert principal_from_claims({"sub": "alice", "exp": now + 300, "nbf": now}, settings)
