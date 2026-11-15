from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from conftest import (
    create_api_key,
    create_org,
    create_user_in_org,
    csrf_headers,
    login,
    setup_org,
)


def _upload(client: TestClient, slug: str, sample_video: Path, name: str = "clip.mp4"):
    with sample_video.open("rb") as handle:
        response = client.post(
            f"/api/v1/orgs/{slug}/videos/upload",
            files={"file": (name, handle, "video/mp4")},
            headers=csrf_headers(client),
        )
    assert response.status_code == 201, response.text
    return response.json()["video"]


def test_other_org_cannot_read_or_stream_video(client: TestClient, sample_video: Path) -> None:
    setup_org(client)
    video = _upload(client, "acme", sample_video)
    create_org(
        name="Globex",
        slug="globex",
        email="owner@globex.com",
        password="senha-muito-segura",
    )

    with TestClient(client.app) as other:
        assert login(other, "owner@globex.com", "senha-muito-segura").status_code == 200
        for path in (
            f"/api/v1/orgs/acme/videos/{video['id']}",
            f"/api/v1/orgs/acme/videos/{video['id']}/stream",
            f"/api/v1/orgs/acme/videos/{video['id']}/thumbnail",
            f"/api/v1/orgs/acme/videos/{video['id']}/events",
        ):
            assert other.get(path).status_code == 404, path
        assert other.get("/api/v1/orgs/acme/videos").status_code == 404


def test_profile_names_are_unique_per_org(client: TestClient) -> None:
    setup_org(client)
    payload = {"name": "Entrada", "masks": [], "settings": {}}
    assert (
        client.post(
            "/api/v1/orgs/acme/profiles", json=payload, headers=csrf_headers(client)
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/orgs/acme/profiles", json=payload, headers=csrf_headers(client)
        ).status_code
        == 409
    )

    create_org(
        name="Globex",
        slug="globex",
        email="owner@globex.com",
        password="senha-muito-segura",
    )
    with TestClient(client.app) as other:
        assert login(other, "owner@globex.com", "senha-muito-segura").status_code == 200
        created = other.post(
            "/api/v1/orgs/globex/profiles",
            json={"name": "Entrada", "masks": [], "settings": {}},
            headers=csrf_headers(other),
        )
        assert created.status_code == 201


def test_api_key_cannot_touch_other_org_upload(client: TestClient) -> None:
    setup_org(client)
    init = client.post(
        "/api/v1/orgs/acme/uploads/init",
        json={"filename": "lote.mp4", "size": 20000},
        headers=csrf_headers(client),
    )
    assert init.status_code == 201
    upload_id = init.json()["upload_id"]

    create_org(
        name="Globex",
        slug="globex",
        email="owner@globex.com",
        password="senha-muito-segura",
    )
    with TestClient(client.app) as other:
        assert login(other, "owner@globex.com", "senha-muito-segura").status_code == 200
        key = create_api_key(other, "globex")
        headers = {"Authorization": f"Bearer {key}"}
        assert (
            other.get(f"/api/v1/ingest/uploads/{upload_id}", headers=headers).status_code
            == 404
        )
        assert (
            other.put(
                f"/api/v1/ingest/uploads/{upload_id}/parts/1",
                content=b"x",
                headers=headers,
            ).status_code
            == 404
        )
        assert (
            other.post(
                f"/api/v1/ingest/uploads/{upload_id}/complete", headers=headers
            ).status_code
            == 404
        )


def test_api_key_ignores_organization_id_in_body(client: TestClient) -> None:
    setup_org(client)
    acme_id = client.get("/api/v1/orgs/acme").json()["id"]
    create_org(
        name="Globex",
        slug="globex",
        email="owner@globex.com",
        password="senha-muito-segura",
    )
    with TestClient(client.app) as other:
        login(other, "owner@globex.com", "senha-muito-segura")
        key = create_api_key(other, "globex")
        response = other.post(
            "/api/v1/ingest/uploads",
            json={
                "filename": "lote.mp4",
                "size": 20000,
                "organization_id": acme_id,
            },
            headers={"Authorization": f"Bearer {key}"},
        )
        assert response.status_code == 201, response.text

    from app.db import SessionLocal
    from app.models import UploadSession

    db = SessionLocal()
    try:
        upload = db.query(UploadSession).one()
        assert upload.organization_id != acme_id
    finally:
        db.close()


def test_api_key_scope_is_enforced(client: TestClient) -> None:
    setup_org(client)
    key = create_api_key(client, "acme", scopes=["videos:read"])
    response = client.post(
        "/api/v1/ingest/uploads",
        json={"filename": "lote.mp4", "size": 20000},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert response.status_code == 403


def test_viewer_cannot_manage_profiles(client: TestClient) -> None:
    setup_org(client)
    create_user_in_org(
        email="viewer@acme.com",
        password="senha-muito-segura",
        organization_slug="acme",
        group_name="Viewer",
    )
    with TestClient(client.app) as viewer:
        assert login(viewer, "viewer@acme.com", "senha-muito-segura").status_code == 200
        assert viewer.get("/api/v1/orgs/acme/profiles").status_code == 200
        denied = viewer.post(
            "/api/v1/orgs/acme/profiles",
            json={"name": "Nova", "masks": [], "settings": {}},
            headers=csrf_headers(viewer),
        )
        assert denied.status_code == 403


def test_cannot_switch_to_foreign_org(client: TestClient) -> None:
    setup_org(client)
    create_org(
        name="Globex",
        slug="globex",
        email="owner@globex.com",
        password="senha-muito-segura",
    )
    response = client.post(
        "/api/v1/auth/switch-organization",
        json={"slug": "globex"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 404


def test_worker_rejects_cross_org_job(client: TestClient) -> None:
    setup_org(client)
    create_org(
        name="Globex",
        slug="globex",
        email="owner@globex.com",
        password="senha-muito-segura",
    )

    from app.db import SessionLocal
    from app.models import Job, Organization, Video
    from app.worker import _process_job

    db = SessionLocal()
    try:
        acme = db.query(Organization).filter(Organization.slug == "acme").one()
        globex = db.query(Organization).filter(Organization.slug == "globex").one()
        video = Video(
            organization_id=globex.id,
            filename="globex.mp4",
            source_path="/tmp/globex.mp4",
            status="uploaded",
        )
        db.add(video)
        db.flush()
        job = Job(
            organization_id=acme.id,
            video_id=video.id,
            status="running",
            stage="starting",
        )
        db.add(job)
        db.commit()
        job_id = job.id
    finally:
        db.close()

    _process_job(job_id)

    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        assert job is not None
        assert job.status == "failed"
        assert "tenancy" in (job.error or "")
    finally:
        db.close()
