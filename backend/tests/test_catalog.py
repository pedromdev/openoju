from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from conftest import csrf_headers, setup_org


def test_profiles_crud(client: TestClient) -> None:
    setup_org(client)
    response = client.get("/api/v1/orgs/acme/profiles")
    assert response.status_code == 200
    assert [profile["name"] for profile in response.json()] == ["Default"]

    created = client.post(
        "/api/v1/orgs/acme/profiles",
        json={
            "name": "Teste",
            "masks": [{"x": 0.0, "y": 0.0, "w": 0.35, "h": 0.1}],
            "roi": None,
            "settings": {},
        },
        headers=csrf_headers(client),
    )
    assert created.status_code == 201
    profile = created.json()
    assert len(profile["masks"]) == 1

    updated = client.put(
        f"/api/v1/orgs/acme/profiles/{profile['id']}",
        json={
            "name": "Teste editado",
            "masks": [],
            "roi": None,
            "settings": {"motion": {"threshold": 0.01}},
        },
        headers=csrf_headers(client),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Teste editado"

    deleted = client.delete(
        f"/api/v1/orgs/acme/profiles/{profile['id']}",
        headers=csrf_headers(client),
    )
    assert deleted.status_code == 204


def test_upload_list_analyze_and_delete(
    client: TestClient, sample_video: Path
) -> None:
    setup_org(client)
    with sample_video.open("rb") as handle:
        response = client.post(
            "/api/v1/orgs/acme/videos/upload",
            files={"file": ("moving.mp4", handle, "video/mp4")},
            headers=csrf_headers(client),
        )
    assert response.status_code == 201
    video = response.json()["video"]
    assert video["status"] == "uploaded"
    assert video["duration_s"] is not None
    assert video["event_count"] == 0

    job_response = client.post(
        f"/api/v1/orgs/acme/videos/{video['id']}/analyze",
        headers=csrf_headers(client),
    )
    assert job_response.status_code == 200
    assert job_response.json()["status"] == "queued"

    listing = client.get("/api/v1/orgs/acme/videos")
    assert listing.status_code == 200
    assert any(item["id"] == video["id"] for item in listing.json())

    assert (
        client.get(f"/api/v1/orgs/acme/videos/{video['id']}/stream").status_code == 404
    )

    client.post(
        f"/api/v1/orgs/acme/jobs/{job_response.json()['id']}/cancel",
        headers=csrf_headers(client),
    )
    deleted = client.delete(
        f"/api/v1/orgs/acme/videos/{video['id']}", headers=csrf_headers(client)
    )
    assert deleted.status_code == 204
    assert (
        client.get(f"/api/v1/orgs/acme/videos/{video['id']}").status_code == 404
    )


def test_upload_dedup_is_per_org(client: TestClient, sample_video: Path) -> None:
    setup_org(client)
    ids = []
    for _ in range(2):
        with sample_video.open("rb") as handle:
            response = client.post(
                "/api/v1/orgs/acme/videos/upload",
                files={"file": ("moving.mp4", handle, "video/mp4")},
                headers=csrf_headers(client),
            )
        assert response.status_code == 201
        ids.append(response.json()["video"]["id"])
    assert ids[0] == ids[1]


def test_import_outside_media_root_is_rejected(client: TestClient) -> None:
    setup_org(client)
    response = client.post(
        "/api/v1/orgs/acme/videos/import",
        json={"path": "/etc/passwd", "recursive": False},
        headers=csrf_headers(client),
    )
    assert response.status_code == 400


def test_access_log_records_video_view(
    client: TestClient, sample_video: Path
) -> None:
    setup_org(client)
    with sample_video.open("rb") as handle:
        video = client.post(
            "/api/v1/orgs/acme/videos/upload",
            files={"file": ("moving.mp4", handle, "video/mp4")},
            headers=csrf_headers(client),
        ).json()["video"]
    assert (
        client.get(f"/api/v1/orgs/acme/videos/{video['id']}").status_code == 200
    )

    from app.db import SessionLocal
    from app.models import AccessLog

    db = SessionLocal()
    try:
        entries = db.query(AccessLog).all()
        assert any(
            entry.action == "view_video" and entry.resource_id == video["id"]
            for entry in entries
        )
    finally:
        db.close()
