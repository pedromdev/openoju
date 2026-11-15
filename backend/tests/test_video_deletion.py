from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from conftest import csrf_headers, create_org, create_user_in_org, login, setup_org


def _org_id(slug: str) -> str:
    from app.db import SessionLocal
    from app.models import Organization

    db = SessionLocal()
    try:
        return db.query(Organization).filter(Organization.slug == slug).one().id
    finally:
        db.close()


def _video(organization_id: str, name: str, *, source: str | None = None, keys: bool = False) -> str:
    from app.db import SessionLocal
    from app.models import Video

    db = SessionLocal()
    try:
        video = Video(
            organization_id=organization_id,
            filename=name,
            source_path=source,
            storage_backend="s3" if keys else "local",
            storage_key=f"org/{organization_id}/videos/{name}" if keys else None,
            proxy_storage_key=f"org/{organization_id}/proxy/{name}.mp4" if keys else None,
            status="ready",
        )
        db.add(video)
        db.commit()
        db.refresh(video)
        return video.id
    finally:
        db.close()


def test_delete_video_and_write_audit(client: TestClient, sample_video: Path) -> None:
    setup_org(client)
    with sample_video.open("rb") as handle:
        video = client.post(
            "/api/v1/orgs/acme/videos/upload",
            files={"file": ("apagar.mp4", handle, "video/mp4")},
            headers=csrf_headers(client),
        ).json()["video"]

    response = client.delete(
        f"/api/v1/orgs/acme/videos/{video['id']}", headers=csrf_headers(client)
    )
    assert response.status_code == 204
    assert client.get(f"/api/v1/orgs/acme/videos/{video['id']}").status_code == 404

    from app.db import SessionLocal
    from app.models import AccessLog, AuditLog, Video

    db = SessionLocal()
    try:
        assert db.get(Video, video["id"]) is None
        assert (
            db.query(AuditLog)
            .filter(AuditLog.action == "video.delete", AuditLog.resource_id == video["id"])
            .count()
            == 1
        )
        assert (
            db.query(AccessLog)
            .filter(AccessLog.action == "delete_video", AccessLog.resource_id == video["id"])
            .count()
            == 1
        )
    finally:
        db.close()


def test_imported_source_is_preserved(client: TestClient, sample_video: Path) -> None:
    setup_org(client)
    video_id = _video(_org_id("acme"), "importado.mp4", source=str(sample_video))
    response = client.delete(
        f"/api/v1/orgs/acme/videos/{video_id}", headers=csrf_headers(client)
    )
    assert response.status_code == 204
    assert sample_video.exists()


def test_legal_hold_blocks_deletion(client: TestClient) -> None:
    setup_org(client)
    video_id = _video(_org_id("acme"), "held.mp4")
    hold = client.post(
        "/api/v1/orgs/acme/legal-holds",
        json={"resource_type": "video", "resource_id": video_id, "reason": "processo"},
        headers=csrf_headers(client),
    )
    assert hold.status_code == 201
    response = client.delete(
        f"/api/v1/orgs/acme/videos/{video_id}", headers=csrf_headers(client)
    )
    assert response.status_code == 409
    assert "legal hold" in response.json()["detail"]


def test_active_job_blocks_deletion_until_cancel(
    client: TestClient, sample_video: Path
) -> None:
    setup_org(client)
    with sample_video.open("rb") as handle:
        video = client.post(
            "/api/v1/orgs/acme/videos/upload",
            files={"file": ("ocupado.mp4", handle, "video/mp4")},
            headers=csrf_headers(client),
        ).json()["video"]
    job = client.post(
        f"/api/v1/orgs/acme/videos/{video['id']}/analyze",
        headers=csrf_headers(client),
    ).json()
    blocked = client.delete(
        f"/api/v1/orgs/acme/videos/{video['id']}", headers=csrf_headers(client)
    )
    assert blocked.status_code == 409
    assert "análise em andamento" in blocked.json()["detail"]

    canceled = client.post(
        f"/api/v1/orgs/acme/jobs/{job['id']}/cancel", headers=csrf_headers(client)
    )
    assert canceled.status_code == 200
    deleted = client.delete(
        f"/api/v1/orgs/acme/videos/{video['id']}", headers=csrf_headers(client)
    )
    assert deleted.status_code == 204


def test_bulk_delete_partial_results(client: TestClient) -> None:
    setup_org(client)
    org_id = _org_id("acme")
    first = _video(org_id, "primeiro.mp4")
    second = _video(org_id, "segundo.mp4")
    hold = client.post(
        "/api/v1/orgs/acme/legal-holds",
        json={"resource_type": "video", "resource_id": second, "reason": "legal"},
        headers=csrf_headers(client),
    )
    assert hold.status_code == 201

    response = client.post(
        "/api/v1/orgs/acme/videos/bulk-delete",
        json={"ids": [first, second, "inexistente"]},
        headers=csrf_headers(client),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] == [first]
    failed = {item["id"]: item for item in payload["failed"]}
    assert failed[second]["status"] == 409
    assert failed["inexistente"]["status"] == 404
    assert (
        client.get(f"/api/v1/orgs/acme/videos/{first}").status_code == 404
    )
    assert (
        client.get(f"/api/v1/orgs/acme/videos/{second}").status_code == 200
    )


def test_viewer_cannot_delete(client: TestClient) -> None:
    setup_org(client)
    video_id = _video(_org_id("acme"), "protegido.mp4")
    create_user_in_org(
        email="viewer2@acme.com",
        password="senha-muito-segura",
        organization_slug="acme",
        group_name="Viewer",
    )
    with TestClient(client.app) as viewer:
        login(viewer, "viewer2@acme.com", "senha-muito-segura")
        response = viewer.delete(
            f"/api/v1/orgs/acme/videos/{video_id}", headers=csrf_headers(viewer)
        )
        assert response.status_code == 403


def test_cross_tenant_delete_is_not_found(client: TestClient) -> None:
    setup_org(client)
    video_id = _video(_org_id("acme"), "acme.mp4")
    create_org(name="Globex", slug="globex", email="owner@globex.com", password="senha-muito-segura")
    with TestClient(client.app) as other:
        login(other, "owner@globex.com", "senha-muito-segura")
        response = other.delete(
            f"/api/v1/orgs/acme/videos/{video_id}", headers=csrf_headers(other)
        )
        assert response.status_code == 404


def test_collect_artifacts_includes_storage_keys() -> None:
    from app.config import get_settings
    from app.models import Event, Video
    from app.services.video_deletion import collect_artifacts

    video = Video(
        id="v1",
        organization_id="org1",
        filename="v.mp4",
        storage_backend="s3",
        storage_key="org/org1/videos/v.mp4",
        proxy_storage_key="org/org1/proxy/v.mp4",
        thumbnail_storage_key="org/org1/thumbs/v.jpg",
        status="ready",
    )
    event = Event(
        id="e1",
        organization_id="org1",
        video_id="v1",
        start_s=0,
        end_s=1,
        clip_storage_key="org/org1/clips/e1.mp4",
        thumbnail_storage_key="org/org1/thumbs/e1.jpg",
    )
    artifacts = collect_artifacts(video, [event], get_settings())
    assert set(artifacts.storage_keys) == {
        "org/org1/videos/v.mp4",
        "org/org1/proxy/v.mp4",
        "org/org1/thumbs/v.jpg",
        "org/org1/clips/e1.mp4",
        "org/org1/thumbs/e1.jpg",
    }
