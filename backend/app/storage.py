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
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=settings.s3_region,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
            # O botocore >= 1.36 envia x-amz-checksum-* por padrão; o GCS em
            # modo interoperabilidade rejeita esses cabeçalhos com
            # SignatureDoesNotMatch. "when_required" mantém S3/MinIO felizes.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
        **credentials,
    )


class S3Storage:
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


class LocalStorage:
    """Local backend uses filesystem paths directly; this class documents it."""

    def ensure_bucket(self) -> None:
        return None


def get_storage(settings: Settings | None = None):
    settings = settings or get_settings()
    if settings.storage_backend == "s3":
        return S3Storage(settings)
    return LocalStorage()
