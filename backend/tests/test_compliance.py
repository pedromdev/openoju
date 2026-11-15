from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import csrf_headers, setup_org


def _org_id(slug: str) -> str:
    from app.db import SessionLocal
    from app.models import Organization

    db = SessionLocal()
    try:
        return db.query(Organization).filter(Organization.slug == slug).one().id
    finally:
        db.close()


def _old_video(organization_id: str, *, days: int = 90, name: str = "old.mp4"):
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import Video

    settings = get_settings()
    path = settings.org_uploads_dir(organization_id) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake")
    db = SessionLocal()
    try:
        video = Video(
            organization_id=organization_id,
            filename=name,
            source_path=str(path),
            status="ready",
            created_at=datetime.now(timezone.utc) - timedelta(days=days),
        )
        db.add(video)
        db.commit()
        db.refresh(video)
        return video.id, path
    finally:
        db.close()


def test_public_privacy_and_dsr_flow(client: TestClient) -> None:
    setup_org(client)
    public = client.get("/api/v1/privacy/acme")
    assert public.status_code == 200
    assert public.json()["organization_slug"] == "acme"
    assert public.json()["retention_media_days"] == 30

    payload = {
        "type": "access",
        "requester_name": "Titular Teste",
        "requester_email": "titular@example.com",
        "description": "Quero saber quais imagens existem",
    }
    created = client.post("/api/v1/privacy/acme/requests", json=payload)
    assert created.status_code == 201, created.text
    dsr = created.json()
    assert dsr["protocol"].startswith("DSR-")
    from app.security import ensure_utc

    due = ensure_utc(datetime.fromisoformat(dsr["due_at"]))
    assert due is not None
    assert (due - datetime.now(timezone.utc)).days >= 14

    listing = client.get("/api/v1/orgs/acme/data-subject-requests")
    assert listing.status_code == 200
    assert listing.json()[0]["protocol"] == dsr["protocol"]

    updated = client.patch(
        f"/api/v1/orgs/acme/data-subject-requests/{dsr['id']}",
        json={"status": "verified", "resolution": "identidade verificada"},
        headers=csrf_headers(client),
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "verified"

    for _ in range(5):
        client.post("/api/v1/privacy/acme/requests", json=payload)
    blocked = client.post("/api/v1/privacy/acme/requests", json=payload)
    assert blocked.status_code == 429


def test_retention_expires_media_and_old_event_metadata(client: TestClient) -> None:
    setup_org(client)
    organization_id = _org_id("acme")
    video_id, path = _old_video(organization_id)

    from app.db import SessionLocal
    from app.models import Event

    db = SessionLocal()
    try:
        old_event = Event(
            organization_id=organization_id,
            video_id=video_id,
            start_s=1.0,
            end_s=2.0,
            clip_path=str(path) + ".clip.mp4",
            created_at=datetime.now(timezone.utc) - timedelta(days=400),
        )
        db.add(old_event)
        db.commit()
        event_id = old_event.id
    finally:
        db.close()

    response = client.post(
        "/api/v1/orgs/acme/retention/run", headers=csrf_headers(client)
    )
    assert response.status_code == 200, response.text
    counts = response.json()
    assert counts["videos_expired"] >= 1
    assert counts["events_deleted"] >= 1
    assert not path.exists()

    db = SessionLocal()
    try:
        from app.models import Video

        video = db.get(Video, video_id)
        assert video.status == "expired"
        assert video.source_path is None
        assert db.get(Event, event_id) is None
    finally:
        db.close()


def test_legal_hold_blocks_media_expiry(client: TestClient) -> None:
    setup_org(client)
    organization_id = _org_id("acme")
    video_id, path = _old_video(organization_id, name="held.mp4")

    hold = client.post(
        "/api/v1/orgs/acme/legal-holds",
        json={"resource_type": "video", "resource_id": video_id, "reason": "processo judicial"},
        headers=csrf_headers(client),
    )
    assert hold.status_code == 201, hold.text

    client.post("/api/v1/orgs/acme/retention/run", headers=csrf_headers(client))
    assert path.exists()

    from app.db import SessionLocal
    from app.models import Video

    db = SessionLocal()
    try:
        assert db.get(Video, video_id).status != "expired"
    finally:
        db.close()


def test_dsr_execute_deletion_respects_legal_hold(client: TestClient) -> None:
    setup_org(client)
    organization_id = _org_id("acme")
    video_id, _path = _old_video(organization_id, days=1, name="dsr.mp4")

    from app.db import SessionLocal
    from app.models import Event

    db = SessionLocal()
    try:
        event = Event(
            organization_id=organization_id,
            video_id=video_id,
            start_s=0.0,
            end_s=1.0,
            clip_path="/tmp/nao-existe.mp4",
        )
        db.add(event)
        db.commit()
        event_id = event.id
    finally:
        db.close()

    dsr = client.post(
        "/api/v1/privacy/acme/requests",
        json={
            "type": "deletion",
            "requester_name": "Titular",
            "requester_email": "titular@example.com",
            "date_range_start": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
            "date_range_end": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
        },
    ).json()

    hold = client.post(
        "/api/v1/orgs/acme/legal-holds",
        json={"resource_type": "event", "resource_id": event_id, "reason": "obrigação legal"},
        headers=csrf_headers(client),
    )
    assert hold.status_code == 201

    result = client.post(
        f"/api/v1/orgs/acme/data-subject-requests/{dsr['id']}/execute-deletion",
        headers=csrf_headers(client),
    )
    assert result.status_code == 200, result.text
    assert result.json()["skipped_legal_hold"] == 1

    export = client.get(f"/api/v1/orgs/acme/data-subject-requests/{dsr['id']}/export")
    assert export.status_code == 200
    assert export.json()["events"][0]["id"] == event_id


def test_access_logs_are_purged_after_retention(client: TestClient) -> None:
    setup_org(client)
    organization_id = _org_id("acme")

    from app.db import SessionLocal
    from app.models import AccessLog

    db = SessionLocal()
    try:
        db.add(
            AccessLog(
                organization_id=organization_id,
                action="view_video",
                created_at=datetime.now(timezone.utc) - timedelta(days=400),
            )
        )
        db.commit()
    finally:
        db.close()

    counts = client.post(
        "/api/v1/orgs/acme/retention/run", headers=csrf_headers(client)
    ).json()
    assert counts["access_logs"] >= 1
