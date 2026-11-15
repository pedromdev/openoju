from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# Configure an isolated app before importing modules that build the SQLAlchemy
# engine and resolve the media root at import time.
_TMP = Path(tempfile.mkdtemp(prefix="openoju-tests-"))
os.environ["OJU_DATA_DIR"] = str(_TMP / "data")
os.environ["OJU_MEDIA_ROOT"] = str(_TMP / "media")
os.environ["OJU_WATCH_DIR"] = str(_TMP / "media" / "inbox")
os.environ["OJU_DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["OJU_AUTO_ANALYZE"] = "false"
os.environ["OJU_BASIC_AUTH_USER"] = ""
os.environ["OJU_BASIC_AUTH_PASSWORD"] = ""
os.environ["OJU_UPLOAD_CHUNK_SIZE"] = "8192"
os.environ["OJU_UPLOAD_SESSION_TTL_HOURS"] = "48"
os.environ["OJU_COOKIE_SECURE"] = "false"
os.environ["OJU_CSRF_ENABLED"] = "true"
os.environ["OJU_SETUP_TOKEN"] = "test-setup-token"
os.environ["OJU_SECRET_KEY"] = "test-secret-key-with-at-least-32-bytes"
os.environ["OJU_FERNET_KEY"] = "0h0n6m8mS0mJ8bqOQ0d1oQ0m9h5V4d7n2o8Q0K0m7xE="
os.environ["OJU_STORAGE_BACKEND"] = "local"
os.environ["OJU_RETENTION_MEDIA_DAYS"] = "30"


@pytest.fixture(scope="session")
def sample_video() -> Path:
    path = _TMP / "moving.mp4"
    if path.exists():
        return path
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x202020:s=640x360:r=10:d=12",
        "-f",
        "lavfi",
        "-i",
        "color=c=white:s=80x80:r=10:d=12",
        "-filter_complex",
        "[0:v][1:v]overlay=x='mod(t*120,400)':y=150:shortest=1",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(cmd, check=True, timeout=120)
    return path


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_database():
    from app.db import Base, engine
    from app.security import login_limiter

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    login_limiter._hits.clear()
    yield


def csrf_headers(client) -> dict[str, str]:
    token = client.cookies.get("openoju_csrf")
    assert token, "csrf cookie ausente"
    return {"X-CSRF-Token": token}


def setup_org(
    client,
    *,
    name: str = "Acme",
    slug: str = "acme",
    email: str = "owner@acme.com",
    password: str = "senha-muito-segura",
    token: str = "test-setup-token",
):
    response = client.post(
        "/api/v1/auth/setup",
        json={
            "token": token,
            "organization_name": name,
            "organization_slug": slug,
            "owner_email": email,
            "owner_password": password,
            "owner_display_name": "Owner Acme",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def login(client, email: str, password: str):
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )


def create_org(
    *,
    name: str,
    slug: str,
    email: str,
    password: str,
):
    from app.db import SessionLocal
    from app.services.organizations import create_organization_with_owner

    db = SessionLocal()
    try:
        organization, _user, _membership = create_organization_with_owner(
            db,
            organization_name=name,
            slug=slug,
            owner_email=email,
            owner_password=password,
            owner_display_name=name,
        )
        return organization.id, organization.slug
    finally:
        db.close()


def create_user_in_org(
    *,
    email: str,
    password: str,
    organization_slug: str,
    group_name: str = "Viewer",
):
    from app.db import SessionLocal
    from app.models import Membership, Organization, PermissionGroup, User, utcnow
    from app.security import hash_password

    db = SessionLocal()
    try:
        organization = (
            db.query(Organization)
            .filter(Organization.slug == organization_slug)
            .one()
        )
        user = User(
            email=email,
            display_name=email.split("@")[0],
            password_hash=hash_password(password),
            email_verified_at=utcnow(),
        )
        db.add(user)
        db.flush()
        membership = Membership(
            user_id=user.id,
            organization_id=organization.id,
            status="active",
        )
        db.add(membership)
        db.flush()
        group = (
            db.query(PermissionGroup)
            .filter(
                PermissionGroup.organization_id == organization.id,
                PermissionGroup.name == group_name,
            )
            .one()
        )
        membership.permission_groups = [group]
        db.commit()
        return user.id
    finally:
        db.close()


def create_api_key(client, slug: str, *, name: str = "key", scopes=None) -> str:
    response = client.post(
        f"/api/v1/orgs/{slug}/api-keys",
        json={"name": name, "scopes": scopes or ["ingest:write"]},
        headers=csrf_headers(client),
    )
    assert response.status_code == 201, response.text
    return response.json()["key"]


def pytest_sessionfinish(session, exitstatus) -> None:
    shutil.rmtree(_TMP, ignore_errors=True)
