from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import csrf_headers, setup_org


class FakeStorage:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.uploaded: dict[str, bytes] = {}

    def open_stream(self, key: str):
        assert key in self.uploaded or self.payload
        return io.BytesIO(self.payload), len(self.payload)

    def upload(self, path: Path, key: str) -> None:
        self.uploaded[key] = Path(path).read_bytes()


def _uploaded_job(client: TestClient, sample_video: Path) -> tuple[str, str]:
    setup_org(client)
    with sample_video.open("rb") as handle:
        response = client.post(
            "/api/v1/orgs/acme/videos/upload",
            files={"file": ("moving.mp4", handle, "video/mp4")},
            headers=csrf_headers(client),
        )
    assert response.status_code == 201, response.text
    video = response.json()["video"]
    job_response = client.post(
        f"/api/v1/orgs/acme/videos/{video['id']}/analyze",
        headers=csrf_headers(client),
    )
    assert job_response.status_code == 200, job_response.text
    return video["id"], job_response.json()["id"]


def test_job_log_is_streamed_from_object_storage(
    client: TestClient, sample_video: Path, monkeypatch
) -> None:
    from app.api import jobs as jobs_api
    from app.db import SessionLocal
    from app.models import Job

    _, job_id = _uploaded_job(client, sample_video)
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        assert job is not None
        job.log_key = "org/acme/logs/job.log"
        job.log_path = "/caminho/que/nao/existe/em/outro/pod/job.log"
        db.commit()
    finally:
        db.close()

    storage = FakeStorage(b"primeira linha\nsegunda linha\n")
    monkeypatch.setattr(jobs_api, "get_storage", lambda settings=None: storage)

    response = client.get(f"/api/v1/orgs/acme/jobs/{job_id}/log")
    assert response.status_code == 200, response.text
    assert response.text == "primeira linha\nsegunda linha\n"


def test_publish_job_log_uploads_and_sets_key(monkeypatch, tmp_path: Path) -> None:
    from app import worker as worker_module
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import Job, Organization, Video

    settings = get_settings().model_copy(
        update={"storage_backend": "s3", "media_root": tmp_path}
    )
    monkeypatch.setattr(worker_module, "_settings", settings)

    storage = FakeStorage(b"")
    monkeypatch.setattr(worker_module, "get_storage", lambda cfg=None: storage)

    db = SessionLocal()
    try:
        organization = Organization(name="Acme", slug="acme-log")
        db.add(organization)
        db.flush()
        video = Video(
            organization_id=organization.id,
            filename="moving.mp4",
            status="uploaded",
            size_bytes=10,
        )
        db.add(video)
        db.flush()
        job = Job(organization_id=organization.id, video_id=video.id)
        db.add(job)
        db.commit()

        log_file = tmp_path / "jobs" / job.id / "job.log"
        log_file.parent.mkdir(parents=True)
        log_file.write_text("linha de log\n", encoding="utf-8")

        worker_module._publish_job_log(db, job.id, log_file)

        refreshed = db.get(Job, job.id)
        assert refreshed is not None
        assert refreshed.log_key == settings.job_log_key(organization.id, job.id)
        assert storage.uploaded[refreshed.log_key] == b"linha de log\n"
    finally:
        db.close()
