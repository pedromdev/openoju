from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from conftest import create_api_key, csrf_headers, setup_org


def _init_upload(client: TestClient, headers: dict[str, str], content: bytes, **extra):
    payload = {"filename": "lote.mp4", "size": len(content), **extra}
    response = client.post(
        "/api/v1/ingest/uploads", json=payload, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_ingest_full_flow(client: TestClient, sample_video: Path) -> None:
    setup_org(client)
    key = create_api_key(client, "acme")
    headers = {"Authorization": f"Bearer {key}"}

    batch = client.post(
        "/api/v1/ingest/batches", json={"name": "Lote de teste"}, headers=headers
    )
    assert batch.status_code == 201
    batch_id = batch.json()["id"]

    content = sample_video.read_bytes()
    upload = _init_upload(client, headers, content, batch_id=batch_id)
    part_size = upload["part_size"]
    assert part_size == 8192
    assert upload["total_parts"] > 1

    for index in range(upload["total_parts"]):
        part = content[index * part_size : (index + 1) * part_size]
        response = client.put(
            f"/api/v1/ingest/uploads/{upload['upload_id']}/parts/{index + 1}",
            content=part,
            headers={**headers, "Content-Type": "application/octet-stream"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["received"] == index + 1

    complete = client.post(
        f"/api/v1/ingest/uploads/{upload['upload_id']}/complete", headers=headers
    )
    assert complete.status_code == 200, complete.text
    video = complete.json()["video"]
    assert video["filename"] == "lote.mp4"
    assert video["status"] == "uploaded"
    assert video["size_bytes"] == len(content)

    fetched_batch = client.get(f"/api/v1/ingest/batches/{batch_id}", headers=headers)
    assert fetched_batch.status_code == 200
    assert fetched_batch.json()["status"] == "completed"

    from app.db import SessionLocal
    from app.models import Organization, Video

    db = SessionLocal()
    try:
        acme = db.query(Organization).filter(Organization.slug == "acme").one()
        stored = db.get(Video, video["id"])
        assert stored.organization_id == acme.id
    finally:
        db.close()


def test_ingest_incomplete_upload(client: TestClient, sample_video: Path) -> None:
    setup_org(client)
    key = create_api_key(client, "acme")
    headers = {"Authorization": f"Bearer {key}"}
    content = sample_video.read_bytes()
    upload = _init_upload(client, headers, content)
    assert (
        client.put(
            f"/api/v1/ingest/uploads/{upload['upload_id']}/parts/1",
            content=content[:8192],
            headers=headers,
        ).status_code
        == 200
    )
    complete = client.post(
        f"/api/v1/ingest/uploads/{upload['upload_id']}/complete", headers=headers
    )
    assert complete.status_code == 409
    assert "partes ausentes" in complete.json()["detail"]


def test_revoked_api_key_is_rejected(client: TestClient) -> None:
    setup_org(client)
    created = client.post(
        "/api/v1/orgs/acme/api-keys",
        json={"name": "temp", "scopes": ["ingest:write"]},
        headers=csrf_headers(client),
    )
    assert created.status_code == 201
    key_id = created.json()["api_key"]["id"]
    key = created.json()["key"]
    revoked = client.delete(
        f"/api/v1/orgs/acme/api-keys/{key_id}", headers=csrf_headers(client)
    )
    assert revoked.status_code == 204
    response = client.get(
        "/api/v1/ingest/batches/anything",
        headers={"Authorization": f"Bearer {key}"},
    )
    assert response.status_code == 401


def test_unknown_api_key_is_rejected(client: TestClient) -> None:
    setup_org(client)
    response = client.post(
        "/api/v1/ingest/uploads",
        json={"filename": "x.mp4", "size": 100},
        headers={"Authorization": "Bearer oju_abcdef_ghijkl"},
    )
    assert response.status_code == 401


def test_ingest_rejects_unsupported_extension(client: TestClient) -> None:
    setup_org(client)
    key = create_api_key(client, "acme")
    response = client.post(
        "/api/v1/ingest/uploads",
        json={"filename": "nota.txt", "size": 100},
        headers={"Authorization": f"Bearer {key}"},
    )
    assert response.status_code == 400
