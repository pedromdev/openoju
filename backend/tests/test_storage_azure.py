from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobBlock

from app import storage as storage_module
from app.config import get_settings
from app.storage import AzureBlobStorage, StorageError, get_storage


class FakeDownloader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self.size = len(data)
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk = self._data[self._pos :]
            self._pos = len(self._data)
        else:
            chunk = self._data[self._pos : self._pos + size]
            self._pos += len(chunk)
        return chunk

    def readall(self) -> bytes:
        return self._data

    def readinto(self, handle) -> int:
        handle.write(self._data)
        return len(self._data)

    def close(self) -> None:
        self.closed = True


class FakeStore:
    def __init__(self) -> None:
        self.blocks: dict[str, bytes] = {}
        self.committed: list[str] = []
        self.content_type: str | None = None
        self.uploaded: bytes | None = None
        self.deleted = False


class FakeBlob:
    def __init__(self, key: str, store: FakeStore) -> None:
        self.key = key
        self.store = store

    @property
    def url(self) -> str:
        return f"https://acct.blob.core.windows.net/media/{self.key}"

    def stage_block(self, block_id: str, data: bytes) -> None:
        self.store.blocks[block_id] = data

    def get_block_list(self, block_list_type: str = "uncommitted"):
        blocks = [BlobBlock(block_id=block_id) for block_id in self.store.blocks]
        return [], blocks

    def commit_block_list(self, blocks, content_settings=None) -> None:
        self.store.committed = [block.id for block in blocks]
        self.store.content_type = getattr(content_settings, "content_type", None)

    def get_blob_properties(self):
        if self.store.deleted or not self.store.blocks:
            raise ResourceNotFoundError("missing")
        return SimpleNamespace(size=sum(len(v) for v in self.store.blocks.values()))

    def download_blob(self):
        if self.store.deleted:
            raise ResourceNotFoundError("missing")
        return FakeDownloader(b"".join(self.store.blocks.values()))

    def upload_blob(self, handle, overwrite=True, content_settings=None) -> None:
        self.store.uploaded = handle.read()
        self.store.content_type = getattr(content_settings, "content_type", None)

    def delete_blob(self, delete_snapshots=None) -> None:
        if self.store.deleted:
            raise ResourceNotFoundError("missing")
        self.store.deleted = True


class FakeContainer:
    def __init__(self) -> None:
        self.stores: dict[str, FakeStore] = {}
        self.created = False
        self.exists = True

    def get_container_properties(self):
        if not self.exists:
            raise ResourceNotFoundError("missing")
        return {}

    def create_container(self) -> None:
        self.created = True
        self.exists = True

    def get_blob_client(self, key: str) -> FakeBlob:
        return FakeBlob(key, self.stores.setdefault(key, FakeStore()))


class FakeService:
    def __init__(self) -> None:
        self.container = FakeContainer()

    def get_container_client(self, name: str) -> FakeContainer:
        return self.container


def build_storage(monkeypatch, **overrides) -> tuple[AzureBlobStorage, FakeService]:
    service = FakeService()
    monkeypatch.setattr(
        storage_module.AzureBlobStorage, "_build_service", lambda self: service
    )
    settings = get_settings().model_copy(
        update={
            "storage_backend": "azure",
            "azure_storage_account": "acct",
            "azure_storage_container": "media",
            **overrides,
        }
    )
    return AzureBlobStorage(settings), service


def test_settings_storage_capabilities():
    s3 = get_settings().model_copy(
        update={"storage_backend": "s3", "s3_part_size": 16 * 1024 * 1024}
    )
    assert s3.uses_object_storage is True
    assert s3.storage_part_size == 16 * 1024 * 1024
    assert s3.storage_presigned_parts is True

    azure = get_settings().model_copy(
        update={"storage_backend": "azure", "azure_block_size": 4 * 1024 * 1024}
    )
    assert azure.uses_object_storage is True
    assert azure.storage_part_size == 4 * 1024 * 1024
    assert azure.storage_presigned_parts is False

    local = get_settings().model_copy(
        update={"storage_backend": "local", "upload_chunk_size": 8192}
    )
    assert local.uses_object_storage is False
    assert local.storage_part_size == 8192
    assert local.storage_presigned_parts is False


def test_get_storage_selects_azure(monkeypatch):
    storage, _ = build_storage(monkeypatch)
    assert isinstance(storage, AzureBlobStorage)
    assert get_storage(storage.settings) is not None


def test_azure_stages_blocks_and_commits(monkeypatch):
    storage, service = build_storage(monkeypatch)
    key = "org/o/videos/v.mp4"
    token = storage.create_multipart(key, content_type="video/mp4")

    assert storage.upload_part(key, token, 1, b"hello ") == storage._block_id(1)
    assert storage.upload_part(key, token, 2, b"world") == storage._block_id(2)
    assert set(storage.list_parts(key, token)) == {1, 2}

    storage.complete_multipart(
        key, token, [{"part_number": 1}, {"part_number": 2}]
    )
    store = service.container.stores[key]
    assert store.committed == [storage._block_id(1), storage._block_id(2)]
    assert store.content_type == "video/mp4"
    assert storage.head_size(key) == 11


def test_azure_download_upload_and_open_stream(monkeypatch, tmp_path):
    storage, service = build_storage(monkeypatch)
    key = "org/o/thumbs/a.jpg"
    service.container.stores[key] = FakeStore()
    service.container.stores[key].blocks[storage._block_id(1)] = b"jpegdata"

    dest = tmp_path / "a.jpg"
    storage.download(key, dest)
    assert dest.read_bytes() == b"jpegdata"

    source = tmp_path / "b.jpg"
    source.write_bytes(b"newdata")
    storage.upload(source, "org/o/thumbs/b.jpg")
    assert service.container.stores["org/o/thumbs/b.jpg"].uploaded == b"newdata"
    assert service.container.stores["org/o/thumbs/b.jpg"].content_type == "image/jpeg"

    reader, length = storage.open_stream(key)
    assert length == 8
    assert reader.read(4) == b"jpeg"
    reader.close()


def test_azure_presign_get_contains_sas(monkeypatch):
    storage, _ = build_storage(
        monkeypatch,
        azure_storage_account_key=base64.b64encode(b"0" * 32).decode(),
    )
    url = storage.presign_get("org/o/videos/v.mp4", expires=600)
    assert url.startswith("https://acct.blob.core.windows.net/media/org/o/videos/v.mp4?")
    assert "sig=" in url
    assert "se=" in url


def test_azure_delete_is_lenient_unless_strict(monkeypatch):
    storage, service = build_storage(monkeypatch)
    key = "org/o/clips/missing.mp4"
    service.container.stores[key] = FakeStore()
    service.container.stores[key].deleted = True

    storage.delete(key)
    with pytest.raises(StorageError):
        storage.delete(key, strict=True)


def test_azure_ensure_container_creates_when_missing(monkeypatch):
    storage, service = build_storage(monkeypatch, azure_create_container=True)
    service.container.exists = False
    storage.ensure_bucket()
    assert service.container.created is True
