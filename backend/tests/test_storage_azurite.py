from __future__ import annotations

import os
import urllib.request
from pathlib import Path

import pytest

from app.config import get_settings
from app.storage import AzureBlobStorage, StorageError

CONNECTION = os.environ.get("AZURITE_CONNECTION_STRING", "")
pytestmark = pytest.mark.skipif(
    not CONNECTION, reason="AZURITE_CONNECTION_STRING não configurada"
)


def _account_key() -> str:
    parts = dict(
        item.split("=", 1) for item in CONNECTION.split(";") if "=" in item
    )
    return parts.get("AccountKey", "")


def test_azurite_roundtrip(tmp_path: Path):
    container = f"openoju-test-{os.urandom(4).hex()}"
    settings = get_settings().model_copy(
        update={
            "storage_backend": "azure",
            "azure_storage_connection_string": CONNECTION,
            "azure_storage_container": container,
            "azure_storage_account": "devstoreaccount1",
            "azure_storage_account_key": _account_key(),
            "azure_create_container": True,
        }
    )
    storage = AzureBlobStorage(settings)
    storage.ensure_bucket()

    key = "org/o/videos/probe.mp4"
    token = storage.create_multipart(key)
    storage.upload_part(key, token, 1, b"hello ")
    storage.upload_part(key, token, 2, b"world")
    assert set(storage.list_parts(key, token)) == {1, 2}
    storage.complete_multipart(
        key, token, [{"part_number": 1}, {"part_number": 2}]
    )

    assert storage.head_size(key) == 11

    dest = tmp_path / "probe.mp4"
    storage.download(key, dest)
    assert dest.read_bytes() == b"hello world"

    reader, length = storage.open_stream(key)
    assert length == 11
    assert reader.read() == b"hello world"
    reader.close()

    url = storage.presign_get(key, expires=300)
    with urllib.request.urlopen(url, timeout=10) as response:
        assert response.read() == b"hello world"

    storage.delete(key)
    with pytest.raises(StorageError):
        storage.head_size(key)
