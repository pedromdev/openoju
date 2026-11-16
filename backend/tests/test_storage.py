from __future__ import annotations

import asyncio
import io
from pathlib import Path

from fastapi import UploadFile


class FakeStorage:
    def __init__(self) -> None:
        self.uploaded: dict[str, int] = {}

    def upload(self, path: Path, key: str) -> None:
        self.uploaded[key] = Path(path).stat().st_size

    def delete(self, key: str, *, strict: bool = False) -> None:
        self.uploaded.pop(key, None)


def test_s3_client_omits_empty_credentials(monkeypatch):
    from app import storage

    captured: dict = {}

    def fake_client(name, **kwargs):
        captured["name"] = name
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(storage.boto3, "client", fake_client)
    settings = storage.get_settings().model_copy(
        update={
            "s3_access_key": "",
            "s3_secret_key": "",
            "s3_internal_endpoint": "http://minio:9000",
        }
    )
    storage._client(settings, public=False)

    assert "aws_access_key_id" not in captured
    assert "aws_secret_access_key" not in captured


def test_s3_client_uses_explicit_credentials(monkeypatch):
    from app import storage

    captured: dict = {}

    def fake_client(name, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(storage.boto3, "client", fake_client)
    settings = storage.get_settings().model_copy(
        update={
            "s3_access_key": "key",
            "s3_secret_key": "secret",
            "s3_internal_endpoint": "http://minio:9000",
        }
    )
    storage._client(settings, public=False)

    assert captured["aws_access_key_id"] == "key"
    assert captured["aws_secret_access_key"] == "secret"


def test_save_upload_with_s3_backend_keeps_no_local_source(
    sample_video: Path, monkeypatch, tmp_path
):
    from app import services
    from app.config import get_settings
    from app.db import SessionLocal
    from app.models import Organization, Video
    from app.services import ingest

    fake = FakeStorage()
    monkeypatch.setattr(ingest, "get_storage", lambda cfg=None: fake)
    settings = get_settings().model_copy(
        update={
            "storage_backend": "s3",
            "media_root": tmp_path,
            "auto_analyze": False,
        }
    )
    settings.ensure_dirs()

    db = SessionLocal()
    try:
        organization = Organization(name="S3 Org", slug="s3-org")
        db.add(organization)
        db.commit()

        upload = UploadFile(
            file=io.BytesIO(sample_video.read_bytes()),
            filename="moving.mp4",
        )
        video, job = asyncio.run(
            ingest.save_upload(
                db,
                upload,
                organization_id=organization.id,
                settings=settings,
            )
        )

        assert job is None
        assert video.storage_backend == "s3"
        assert video.source_path is None
        assert video.storage_key
        assert fake.uploaded[video.storage_key] == sample_video.stat().st_size
        stored = db.get(Video, video.id)
        assert stored is not None
        assert stored.storage_key == video.storage_key
    finally:
        db.close()
        services  # keep the import referenced for linters


def test_s3_client_falls_back_to_public_endpoint(monkeypatch):
    from app import storage

    captured: dict = {}

    def fake_client(name, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(storage.boto3, "client", fake_client)
    settings = storage.get_settings().model_copy(
        update={
            "s3_endpoint": "https://s3.us-east-1.amazonaws.com",
            "s3_internal_endpoint": "",
            "s3_access_key": "key",
            "s3_secret_key": "secret",
        }
    )
    storage._client(settings, public=False)
    assert captured["endpoint_url"] == "https://s3.us-east-1.amazonaws.com"


def test_s3_client_disables_optional_checksums(monkeypatch):
    from app import storage

    captured: dict = {}

    def fake_client(name, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(storage.boto3, "client", fake_client)
    storage._client(
        storage.get_settings().model_copy(
            update={
                "s3_internal_endpoint": "https://storage.googleapis.com",
                "s3_access_key": "key",
                "s3_secret_key": "secret",
            }
        ),
        public=False,
    )
    config = captured["config"]
    assert config.request_checksum_calculation == "when_required"
    assert config.response_checksum_validation == "when_required"
