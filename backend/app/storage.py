from __future__ import annotations

from pathlib import Path
from typing import Any

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from .config import Settings, get_settings

CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class StorageError(RuntimeError):
    pass


def _client(settings: Settings, *, public: bool):
    if public:
        endpoint = settings.s3_endpoint or settings.s3_internal_endpoint
    else:
        endpoint = settings.s3_internal_endpoint or settings.s3_endpoint
    if not endpoint:
        raise StorageError("endpoint S3 não configurado")
    credentials = {}
    if settings.s3_access_key and settings.s3_secret_key:
        credentials["aws_access_key_id"] = settings.s3_access_key
        credentials["aws_secret_access_key"] = settings.s3_secret_key
    addressing = settings.s3_addressing_style
    if addressing not in {"path", "virtual", "auto"}:
        addressing = "path"
    checksums = settings.s3_checksums
    if checksums not in {"when_supported", "when_required"}:
        checksums = "when_required"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=settings.s3_region,
        config=Config(
            signature_version=settings.s3_signature_version or "s3v4",
            s3={"addressing_style": addressing},
            retries={"max_attempts": 3, "mode": "standard"},
            # O botocore >= 1.36 envia x-amz-checksum-* por padrão; o GCS em
            # modo interoperabilidade rejeita esses cabeçalhos com
            # SignatureDoesNotMatch. "when_required" mantém S3/MinIO felizes.
            request_checksum_calculation=checksums,
            response_checksum_validation=checksums,
        ),
        **credentials,
    )


class S3Storage:
    supports_presigned_parts = True
    supports_presigned_get = True

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.bucket = self.settings.s3_bucket
        self._server = _client(self.settings, public=False)
        self._public = _client(self.settings, public=True)

    # -- bucket ---------------------------------------------------------
    def ensure_bucket(self) -> None:
        try:
            self._server.head_bucket(Bucket=self.bucket)
        except ClientError:
            if not self.settings.s3_create_bucket:
                raise StorageError(
                    f"bucket {self.bucket!r} não encontrado e criação desabilitada"
                ) from None
            try:
                self._server.create_bucket(Bucket=self.bucket)
            except (ClientError, BotoCoreError) as exc:
                raise StorageError(f"falha ao criar bucket: {exc}") from exc
        try:
            self._server.put_bucket_cors(
                Bucket=self.bucket,
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedOrigins": self.settings.cors_origin_list,
                            "AllowedMethods": ["GET", "PUT", "HEAD"],
                            "AllowedHeaders": ["*"],
                            "ExposeHeaders": ["ETag"],
                            "MaxAgeSeconds": 3600,
                        }
                    ]
                },
            )
        except (ClientError, BotoCoreError):
            # CORS may be restricted by the provider; uploads can still work
            # for non-browser clients.
            pass

    # -- multipart ------------------------------------------------------
    def create_multipart(self, key: str, content_type: str | None = None) -> str:
        kwargs: dict[str, Any] = {"Bucket": self.bucket, "Key": key}
        if content_type:
            kwargs["ContentType"] = content_type
        try:
            response = self._server.create_multipart_upload(**kwargs)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"falha ao iniciar multipart: {exc}") from exc
        return response["UploadId"]

    def presign_part(
        self, key: str, upload_id: str, part_number: int, expires: int = 3600
    ) -> str:
        return self._public.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "UploadId": upload_id,
                "PartNumber": part_number,
            },
            ExpiresIn=expires,
        )

    def upload_part(
        self, key: str, upload_id: str, part_number: int, data: bytes
    ) -> str:
        try:
            response = self._server.upload_part(
                Bucket=self.bucket,
                Key=key,
                UploadId=upload_id,
                PartNumber=part_number,
                Body=data,
            )
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"falha ao enviar parte: {exc}") from exc
        return str(response.get("ETag", "")).strip('"')

    def list_parts(self, key: str, upload_id: str) -> dict[int, str]:
        parts: dict[int, str] = {}
        marker = 0
        try:
            while True:
                response = self._server.list_parts(
                    Bucket=self.bucket,
                    Key=key,
                    UploadId=upload_id,
                    PartNumberMarker=marker,
                )
                for part in response.get("Parts", []):
                    parts[int(part["PartNumber"])] = str(part["ETag"]).strip('"')
                if not response.get("IsTruncated"):
                    break
                marker = int(response.get("NextPartNumberMarker", 0))
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"falha ao listar partes: {exc}") from exc
        return parts

    def complete_multipart(
        self, key: str, upload_id: str, parts: list[dict[str, Any]]
    ) -> None:
        try:
            self._server.complete_multipart_upload(
                Bucket=self.bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={
                    "Parts": [
                        {"PartNumber": int(part["part_number"]), "ETag": part["etag"]}
                        for part in sorted(parts, key=lambda item: int(item["part_number"]))
                    ]
                },
            )
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"falha ao concluir multipart: {exc}") from exc

    def abort_multipart(self, key: str, upload_id: str) -> None:
        try:
            self._server.abort_multipart_upload(
                Bucket=self.bucket, Key=key, UploadId=upload_id
            )
        except (ClientError, BotoCoreError):
            pass

    # -- objects --------------------------------------------------------
    def head_size(self, key: str) -> int:
        try:
            response = self._server.head_object(Bucket=self.bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"objeto não encontrado: {exc}") from exc
        return int(response["ContentLength"])

    def download(self, key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._server.download_file(self.bucket, key, str(destination))
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"falha ao baixar objeto: {exc}") from exc
        return destination

    def upload(self, path: Path, key: str) -> None:
        content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        try:
            self._server.upload_file(
                str(path),
                self.bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"falha ao enviar objeto: {exc}") from exc

    def presign_get(self, key: str, expires: int = 3600) -> str:
        return self._public.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires,
        )

    def delete(self, key: str, *, strict: bool = False) -> None:
        try:
            self._server.delete_object(Bucket=self.bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            if strict:
                raise StorageError(f"falha ao excluir objeto {key}: {exc}") from exc

    def read_bytes(self, key: str) -> bytes:
        try:
            response = self._server.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"falha ao ler objeto {key}: {exc}") from exc

    def open_stream(self, key: str):
        """Return ``(body, content_length)`` for streaming without loading it all."""
        try:
            response = self._server.get_object(Bucket=self.bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(f"falha ao ler objeto {key}: {exc}") from exc
        body = response["Body"]
        length = int(response.get("ContentLength", 0))
        return body, length


class _AzureReader:
    """Adapt the Azure downloader to the read/close interface used by the API."""

    def __init__(self, downloader) -> None:
        self._downloader = downloader

    def read(self, size: int = -1) -> bytes:
        return self._downloader.read(size)

    def close(self) -> None:
        close = getattr(self._downloader, "close", None)
        if close is not None:
            close()


class AzureBlobStorage:
    """Native Azure Blob Storage backend.

    Azure Blob is not S3-compatible. Multipart uploads map to staged blocks and
    read URLs come from a SAS token (user delegation, falling back to the
    account key). When neither is available, callers stream through the API.
    """

    supports_presigned_parts = False
    supports_presigned_get = True

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.container = self.settings.azure_storage_container
        self._service = self._build_service()
        self._container_client = self._service.get_container_client(self.container)
        self._delegation_key = None

    # -- client ---------------------------------------------------------
    def _build_service(self):
        from azure.storage.blob import BlobServiceClient

        if self.settings.azure_storage_connection_string:
            return BlobServiceClient.from_connection_string(
                self.settings.azure_storage_connection_string
            )
        endpoint = self.settings.azure_endpoint
        if not endpoint:
            raise StorageError(
                "Azure Storage não configurado: defina OJU_AZURE_STORAGE_ACCOUNT"
            )
        from azure.identity import DefaultAzureCredential

        return BlobServiceClient(
            account_url=endpoint, credential=DefaultAzureCredential()
        )

    def _blob(self, key: str):
        return self._container_client.get_blob_client(key)

    @staticmethod
    def _block_id(number: int) -> str:
        import base64

        # Azure exige block ids do mesmo tamanho.
        return base64.b64encode(f"{int(number):08d}".encode()).decode()

    @staticmethod
    def _content_type(key: str) -> str:
        suffix = Path(key).suffix.lower()
        if suffix in {".mp4", ".dav"}:
            return "video/mp4"
        if suffix in {".jpg", ".jpeg"}:
            return "image/jpeg"
        if suffix == ".log":
            return "text/plain; charset=utf-8"
        return "application/octet-stream"

    # -- container ------------------------------------------------------
    def ensure_bucket(self) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self._container_client.get_container_properties()
        except ResourceNotFoundError:
            if not self.settings.azure_create_container:
                raise StorageError(
                    f"container {self.container!r} não encontrado e criação desabilitada"
                ) from None
            try:
                self._container_client.create_container()
            except Exception as exc:  # noqa: BLE001 - surfaced as StorageError
                raise StorageError(f"falha ao criar container: {exc}") from exc

    # -- multipart (staged blocks) --------------------------------------
    def create_multipart(self, key: str, content_type: str | None = None) -> str:
        # O Blob não tem upload id; os blocos ficam pendurados no próprio blob.
        import uuid

        return uuid.uuid4().hex

    def presign_part(
        self, key: str, upload_id: str, part_number: int, expires: int = 3600
    ) -> str:
        raise StorageError(
            "upload direto por parte não é suportado no Azure; use o relay da API"
        )

    def upload_part(
        self, key: str, upload_id: str, part_number: int, data: bytes
    ) -> str:
        block_id = self._block_id(part_number)
        try:
            self._blob(key).stage_block(block_id, data)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"falha ao enviar bloco: {exc}") from exc
        return block_id

    def list_parts(self, key: str, upload_id: str) -> dict[int, str]:
        import base64

        try:
            result = self._blob(key).get_block_list(block_list_type="uncommitted")
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"falha ao listar blocos: {exc}") from exc
        if isinstance(result, tuple):
            uncommitted = result[1]
        else:
            uncommitted = getattr(result, "uncommitted_blocks", [])
        parts: dict[int, str] = {}
        for block in uncommitted:
            block_id = getattr(block, "id", None) or getattr(block, "block_id", "")
            try:
                number = int(base64.b64decode(block_id).decode())
            except (ValueError, TypeError):
                continue
            parts[number] = block_id
        return parts

    def complete_multipart(
        self, key: str, upload_id: str, parts: list[dict[str, Any]]
    ) -> None:
        from azure.storage.blob import BlobBlock, ContentSettings

        blocks = [
            BlobBlock(block_id=self._block_id(int(part["part_number"])))
            for part in sorted(parts, key=lambda item: int(item["part_number"]))
        ]
        try:
            self._blob(key).commit_block_list(
                blocks,
                content_settings=ContentSettings(
                    content_type=self._content_type(key)
                ),
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"falha ao concluir upload: {exc}") from exc

    def abort_multipart(self, key: str, upload_id: str) -> None:
        # Blocos não commitados expiram sozinhos (7 dias).
        return None

    # -- objects --------------------------------------------------------
    def head_size(self, key: str) -> int:
        try:
            return int(self._blob(key).get_blob_properties().size)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"objeto não encontrado: {exc}") from exc

    def download(self, key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("wb") as handle:
                self._blob(key).download_blob().readinto(handle)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"falha ao baixar objeto: {exc}") from exc
        return destination

    def upload(self, path: Path, key: str) -> None:
        from azure.storage.blob import ContentSettings

        try:
            with Path(path).open("rb") as handle:
                self._blob(key).upload_blob(
                    handle,
                    overwrite=True,
                    content_settings=ContentSettings(
                        content_type=self._content_type(key)
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"falha ao enviar objeto: {exc}") from exc

    def _user_delegation_key(self):
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        if self._delegation_key is not None and self._delegation_key.signed_expiry > now:
            return self._delegation_key
        try:
            self._delegation_key = self._service.get_user_delegation_key(
                key_start_time=now - timedelta(minutes=5),
                key_expiry_time=now + timedelta(hours=1),
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"falha ao obter user delegation key: {exc}") from exc
        return self._delegation_key

    def presign_get(self, key: str, expires: int = 3600) -> str:
        from datetime import datetime, timedelta, timezone
        from urllib.parse import urlsplit, urlunsplit

        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        account = self.settings.azure_storage_account
        if not account:
            raise StorageError("conta Azure não configurada para assinar URL")
        expiry = datetime.now(timezone.utc) + timedelta(seconds=expires)
        kwargs: dict[str, Any] = {
            "account_name": account,
            "container_name": self.container,
            "blob_name": key,
            "permission": BlobSasPermissions(read=True),
            "expiry": expiry,
        }
        if self.settings.azure_storage_account_key:
            kwargs["account_key"] = self.settings.azure_storage_account_key
        else:
            kwargs["user_delegation_key"] = self._user_delegation_key()
        try:
            sas = generate_blob_sas(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"falha ao assinar URL: {exc}") from exc
        url = f"{self._blob(key).url}?{sas}"
        public = self.settings.azure_storage_public_endpoint.rstrip("/")
        if public:
            base = urlsplit(url)
            target = urlsplit(public)
            url = urlunsplit(
                (target.scheme, target.netloc, base.path, base.query, base.fragment)
            )
        return url

    def delete(self, key: str, *, strict: bool = False) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self._blob(key).delete_blob(delete_snapshots="include")
        except ResourceNotFoundError:
            if strict:
                raise StorageError(f"objeto {key} não encontrado") from None
        except Exception as exc:  # noqa: BLE001
            if strict:
                raise StorageError(f"falha ao excluir objeto {key}: {exc}") from exc

    def read_bytes(self, key: str) -> bytes:
        try:
            return self._blob(key).download_blob().readall()
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"falha ao ler objeto {key}: {exc}") from exc

    def open_stream(self, key: str):
        try:
            downloader = self._blob(key).download_blob()
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"falha ao ler objeto {key}: {exc}") from exc
        return _AzureReader(downloader), int(downloader.size)


class LocalStorage:
    """Local backend uses filesystem paths directly; this class documents it."""

    supports_presigned_parts = False
    supports_presigned_get = False

    def ensure_bucket(self) -> None:
        return None


def get_storage(settings: Settings | None = None):
    settings = settings or get_settings()
    backend = settings.storage_backend.lower()
    if backend == "s3":
        return S3Storage(settings)
    if backend == "azure":
        return AzureBlobStorage(settings)
    return LocalStorage()
