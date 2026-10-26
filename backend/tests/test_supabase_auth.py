from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api import dependencies
from app.core.config import Settings
from app.core import supabase_auth
from app.infrastructure.db.base import Base
from app.infrastructure.db.models import OperatorRoleRecord


@pytest.fixture()
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def access_token(signing_key, *, audience: str = "authenticated", issuer: str = "https://agro-test.supabase.co/auth/v1") -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": "auth-user-1",
            "aud": audience,
            "iss": issuer,
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "role": "authenticated",
        },
        signing_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def patch_jwks(monkeypatch: pytest.MonkeyPatch, signing_key) -> None:
    class FakeJwksClient:
        def get_signing_key_from_jwt(self, token: str):
            del token
            return SimpleNamespace(key=signing_key.public_key())

    monkeypatch.setattr(supabase_auth, "_jwks_client", lambda _url: FakeJwksClient())


def test_supabase_access_token_checks_signature_issuer_audience_and_expiry(
    monkeypatch: pytest.MonkeyPatch,
    signing_key,
) -> None:
    patch_jwks(monkeypatch, signing_key)
    settings = Settings(_env_file=None, SUPABASE_URL="https://agro-test.supabase.co")

    claims = supabase_auth.verify_supabase_access_token(access_token(signing_key), settings)

    assert claims["sub"] == "auth-user-1"
    with pytest.raises(jwt.InvalidAudienceError):
        supabase_auth.verify_supabase_access_token(access_token(signing_key, audience="anon"), settings)
    with pytest.raises(jwt.InvalidIssuerError):
        supabase_auth.verify_supabase_access_token(access_token(signing_key, issuer="https://wrong.example/auth/v1"), settings)


def test_supabase_access_token_rejects_expired_and_non_asymmetric_tokens(
    monkeypatch: pytest.MonkeyPatch,
    signing_key,
) -> None:
    patch_jwks(monkeypatch, signing_key)
    settings = Settings(_env_file=None, SUPABASE_URL="https://agro-test.supabase.co")
    now = datetime.now(UTC)
    expired = jwt.encode(
        {
            "sub": "auth-user-1",
            "aud": "authenticated",
            "iss": "https://agro-test.supabase.co/auth/v1",
            "iat": now - timedelta(minutes=2),
            "exp": now - timedelta(minutes=1),
        },
        signing_key,
        algorithm="RS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        supabase_auth.verify_supabase_access_token(expired, settings)

    legacy = jwt.encode(
        {
            "sub": "auth-user-1",
            "aud": "authenticated",
            "iss": "https://agro-test.supabase.co/auth/v1",
            "iat": now,
            "exp": now + timedelta(minutes=10),
        },
        "symmetric-test-secret-that-is-long-enough-32bytes",
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidAlgorithmError):
        supabase_auth.verify_supabase_access_token(legacy, settings)


def test_shared_backoffice_role_comes_from_server_database_not_headers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'auth_roles.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    with factory.begin() as session:
        session.add(
            OperatorRoleRecord(
                user_id="auth-user-1",
                role="operator",
                assigned_by_user_id="admin-1",
            )
        )
    settings = Settings(
        _env_file=None,
        APP_ENV="staging",
        STORAGE_BACKEND="sql",
        DATABASE_URL="sqlite://unused",
        SUPABASE_URL="https://agro-test.supabase.co",
    )
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    monkeypatch.setattr(dependencies, "get_session_factory", lambda _database_url: factory)
    monkeypatch.setattr(
        dependencies,
        "verify_supabase_access_token",
        lambda _token, _settings: {"sub": "auth-user-1"},
    )

    result = dependencies.require_operator_user(
        x_operator_user_id="spoofed-admin",
        x_operator_role="admin",
        authorization="Bearer synthetic-token",
    )

    assert result.user_id == "auth-user-1"
    assert result.role == "operator"
    engine.dispose()
