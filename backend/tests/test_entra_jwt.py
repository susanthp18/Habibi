"""Entra access-token accept/reject. No network, no database."""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import entra

TID = "9f2e2b7d-6081-4b3a-b7f5-433b581f6a5f"
AUD = "8b5d91de-0bc3-4763-9bcd-809f42f9f003"
OID = str(uuid.uuid4())


@pytest.fixture()
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def entra_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENTRA_TENANT_ID", TID)
    monkeypatch.setenv("ENTRA_API_AUDIENCE", AUD)
    monkeypatch.setenv("ENTRA_BOOTSTRAP_ADMIN_UPNS", "susanth.p@bigtapp.ai")


def _claims(**overrides) -> dict:
    now = int(time.time())
    body = {
        "iss": f"https://login.microsoftonline.com/{TID}/v2.0",
        "aud": AUD,
        "exp": now + 3600,
        "nbf": now - 60,
        "iat": now,
        "tid": TID,
        "oid": OID,
        "ver": "2.0",
        "scp": "access_as_user",
        "preferred_username": "someone@bigtapp.ai",
        "name": "Someone Example",
        "sub": "sub-1",
    }
    body.update(overrides)
    return body


def _token(key, claims: dict) -> str:
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})


def test_rs256_backend_has_cryptography() -> None:
    from jwt.algorithms import has_crypto

    assert has_crypto, "Entra RS256 verification needs cryptography installed"
    assert entra.looks_like_jwt("") is False
    assert entra.looks_like_jwt("priya-secret") is False
    assert entra.looks_like_jwt("a.b") is False
    token = jwt.encode({"x": 1}, "secret", algorithm="HS256")
    assert entra.looks_like_jwt(token) is True


def test_accepts_a_valid_v2_user_token(rsa_key, entra_env) -> None:
    token = _token(rsa_key, _claims())
    claims = entra.validate_access_token(token, signing_key=rsa_key.public_key())
    assert claims["oid"] == OID


def test_rejects_wrong_tid(rsa_key, entra_env) -> None:
    other = "11111111-1111-1111-1111-111111111111"
    claims = _claims(tid=other, iss=f"https://login.microsoftonline.com/{other}/v2.0")
    token = _token(rsa_key, claims)
    with pytest.raises(entra.EntraAuthError):
        entra.validate_access_token(token, signing_key=rsa_key.public_key())


def test_rejects_msa_tenant(rsa_key, entra_env) -> None:
    claims = _claims(tid=entra.MSA_TENANT_ID)
    token = _token(rsa_key, claims)
    with pytest.raises(entra.EntraAuthError):
        entra.validate_access_token(token, signing_key=rsa_key.public_key())


def test_rejects_guest_ext_upn(rsa_key, entra_env) -> None:
    claims = _claims(preferred_username="user_gmail.com#EXT#@bigtapp.ai")
    token = _token(rsa_key, claims)
    with pytest.raises(entra.EntraAuthError):
        entra.validate_access_token(token, signing_key=rsa_key.public_key())


def test_rejects_guest_acct(rsa_key, entra_env) -> None:
    token = _token(rsa_key, _claims(acct=1))
    with pytest.raises(entra.EntraAuthError):
        entra.validate_access_token(token, signing_key=rsa_key.public_key())


def test_accepts_api_scheme_audience(rsa_key, entra_env) -> None:
    token = _token(rsa_key, _claims(aud=f"api://{AUD}"))
    claims = entra.validate_access_token(token, signing_key=rsa_key.public_key())
    assert claims["oid"] == OID


def test_rejects_wrong_audience(rsa_key, entra_env) -> None:
    token = _token(rsa_key, _claims(aud="00000003-0000-0000-c000-000000000000"))
    with pytest.raises(entra.EntraAuthError):
        entra.validate_access_token(token, signing_key=rsa_key.public_key())


def test_rejects_expired(rsa_key, entra_env) -> None:
    token = _token(rsa_key, _claims(exp=int(time.time()) - 120))
    with pytest.raises(entra.EntraAuthError):
        entra.validate_access_token(token, signing_key=rsa_key.public_key())


def test_rejects_app_only_token(rsa_key, entra_env) -> None:
    token = _token(rsa_key, _claims(idtyp="app"))
    with pytest.raises(entra.EntraAuthError):
        entra.validate_access_token(token, signing_key=rsa_key.public_key())


def test_rejects_missing_scope(rsa_key, entra_env) -> None:
    token = _token(rsa_key, _claims(scp="User.Read"))
    with pytest.raises(entra.EntraAuthError):
        entra.validate_access_token(token, signing_key=rsa_key.public_key())


def test_rejects_v1_ver(rsa_key, entra_env) -> None:
    token = _token(rsa_key, _claims(ver="1.0"))
    with pytest.raises(entra.EntraAuthError):
        entra.validate_access_token(token, signing_key=rsa_key.public_key())
