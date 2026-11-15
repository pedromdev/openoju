from __future__ import annotations

import hashlib
import math
import shutil
from datetime import timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import Job, UploadSession, Video, new_id, utcnow
from ..security import ensure_utc
from ..storage import StorageError, get_storage
from .ffmpeg import FfmpegError, probe_video
from .ingest import VIDEO_SUFFIXES, find_duplicate, safe_filename
from .jobs import enqueue_video, latest_job_for_video

_bucket_ready = False


class IncompleteUpload(ValueError):
    def __init__(self, missing: list[int]) -> None:
        super().__init__(f"partes ausentes: {missing[:50]}")
        self.missing = missing


def _part_dir(session: UploadSession, settings: Settings) -> Path:
    return settings.uploads_tmp_dir / session.id


def _part_path(session: UploadSession, part_number: int, settings: Settings) -> Path:
    return _part_dir(session, settings) / f"{part_number:08d}.part"


def _expected_part_size(session: UploadSession, part_number: int) -> int:
    if part_number < session.total_parts:
        return session.part_size
    return session.total_size - session.part_size * (session.total_parts - 1)


def _storage(settings: Settings):
    global _bucket_ready
    storage = get_storage(settings)
    if not _bucket_ready:
        storage.ensure_bucket()
        _bucket_ready = True
    return storage


def create_session(
    db: Session,
    *,
    organization_id: str,
    filename: str,
    size: int,
    profile_id: str | None = None,
    batch_id: str | None = None,
    settings: Settings | None = None,
) -> UploadSession:
    settings = settings or get_settings()
    settings.ensure_org_dirs(organization_id)
    clean_name = safe_filename(filename)
    suffix = Path(clean_name).suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise ValueError(f"extensão não suportada: {suffix or 'sem extensão'}")
    if size <= 0:
        raise ValueError("tamanho inválido")
    if size > settings.upload_max_bytes:
        raise ValueError("arquivo maior que o limite configurado")
    free, _used, _total = shutil.disk_usage(settings.media_root)
    if settings.storage_backend != "s3" and size + 256 * 1024 * 1024 > free:
        raise OSError("espaço insuficiente no SSD de mídia")

    backend = settings.storage_backend
    part_size = settings.s3_part_size if backend == "s3" else settings.upload_chunk_size
    part_size = max(1, int(part_size))
    total_parts = int(math.ceil(size / part_size))
    upload_id = new_id()
    object_key = settings.storage_key(
        organization_id, "videos", f"{upload_id}-{clean_name}"
    )
    storage_upload_id = None
    if backend == "s3":
        try:
            storage_upload_id = _storage(settings).create_multipart(
                object_key, content_type="video/mp4"
            )
        except StorageError as exc:
            raise OSError(str(exc)) from exc

    upload = UploadSession(
        id=upload_id,
        organization_id=organization_id,
        batch_id=batch_id,
        filename=clean_name,
        total_size=size,
        part_size=part_size,
        total_parts=total_parts,
        parts=[],
        storage_backend=backend,
        storage_upload_id=storage_upload_id,
        object_key=object_key,
        profile_id=profile_id,
        status="uploading",
    )
    db.add(upload)
    db.commit()
    db.refresh(upload)
    if backend == "local":
        _part_dir(upload, settings).mkdir(parents=True, exist_ok=True)
    return upload


def part_urls(session: UploadSession, expires: int | None = None) -> list[str]:
    if session.storage_backend != "s3" or not session.storage_upload_id:
        return []
    settings = get_settings()
    storage = _storage(settings)
    expires = expires or settings.s3_presign_expires_s
    return [
        storage.presign_part(
            session.object_key or "",
            session.storage_upload_id,
            number,
            expires=expires,
        )
        for number in range(1, session.total_parts + 1)
    ]


def get_session(db: Session, upload_id: str) -> UploadSession | None:
    return db.get(UploadSession, upload_id)


def received_parts(session: UploadSession, settings: Settings) -> list[int]:
    if session.storage_backend == "s3":
        return sorted(
            int(part["part_number"]) for part in (session.parts or [])
        )
    directory = _part_dir(session, settings)
    if not directory.exists():
        return []
    parts: list[int] = []
    for path in directory.glob("*.part"):
        try:
            number = int(path.stem)
        except ValueError:
            continue
        if 1 <= number <= session.total_parts:
            parts.append(number)
    return sorted(set(parts))


def _sync_parts(db: Session, session: UploadSession, settings: Settings) -> list[int]:
    parts = received_parts(session, settings)
    session.parts = [
        {
            "part_number": number,
            "size": _part_path(session, number, settings).stat().st_size,
            "etag": None,
        }
        for number in parts
    ]
    return parts


def save_part(
    db: Session,
    session: UploadSession,
    part_number: int,
    data: bytes,
    settings: Settings | None = None,
) -> int:
    settings = settings or get_settings()
    if part_number < 1 or part_number > session.total_parts:
        raise IndexError("número da parte fora do intervalo")
    if not data:
        raise ValueError("parte vazia")
    if len(data) > session.part_size:
        raise ValueError("parte maior que o tamanho permitido")
    expected = _expected_part_size(session, part_number)
    if part_number < session.total_parts and len(data) != expected:
        raise ValueError("parte com tamanho diferente do esperado")
    if part_number == session.total_parts and len(data) != expected:
        raise ValueError("última parte com tamanho diferente do esperado")
    if session.storage_backend == "s3":
        if not session.storage_upload_id:
            raise ValueError("upload multipart não está mais ativo")
        storage = _storage(settings)
        etag = storage.upload_part(
            session.object_key or "",
            session.storage_upload_id,
            part_number,
            data,
        )
        known = {
            int(part["part_number"]): part for part in (session.parts or [])
        }
        known[part_number] = {
            "part_number": part_number,
            "size": len(data),
            "etag": etag,
        }
        session.parts = [known[key] for key in sorted(known)]
        session.status = "uploading"
        session.error = None
        db.commit()
        return len(session.parts)
    directory = _part_dir(session, settings)
    directory.mkdir(parents=True, exist_ok=True)
    target = _part_path(session, part_number, settings)
    temp = target.with_suffix(".tmp")
    temp.write_bytes(data)
    temp.replace(target)
    parts = _sync_parts(db, session, settings)
    session.status = "uploading"
    session.error = None
    db.commit()
    return len(parts)


def _cleanup_session(db: Session, session: UploadSession, settings: Settings) -> None:
    if session.storage_backend == "s3" and session.storage_upload_id:
        _storage(settings).abort_multipart(
            session.object_key or "", session.storage_upload_id
        )
    shutil.rmtree(_part_dir(session, settings), ignore_errors=True)
    db.delete(session)
    db.commit()


def _register_video(
    db: Session,
    session: UploadSession,
    *,
    checksum: str,
    probe,
    size_bytes: int,
    settings: Settings,
) -> tuple[Video, Job | None]:
    existing = find_duplicate(db, session.organization_id, sha256=checksum)
    if existing is not None:
        return existing, latest_job_for_video(db, existing.id, session.organization_id)
    video = Video(
        id=session.id,
        organization_id=session.organization_id,
        filename=session.filename,
        source_path=None if session.storage_backend == "s3" else str(
            settings.org_uploads_dir(session.organization_id)
            / f"{session.id}-{safe_filename(session.filename)}"
        ),
        storage_backend=session.storage_backend,
        storage_key=session.object_key,
        sha256=checksum,
        size_bytes=size_bytes,
        duration_s=probe.duration_s,
        fps=probe.fps,
        width=probe.width,
        height=probe.height,
        video_codec=probe.video_codec,
        audio_codec=probe.audio_codec,
        recorded_at=probe.recorded_at,
        status="uploaded",
        profile_id=session.profile_id,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    job = enqueue_video(db, video) if settings.auto_analyze else None
    return video, job


def complete_session(
    db: Session,
    session: UploadSession,
    settings: Settings | None = None,
    parts: list[dict] | None = None,
) -> tuple[Video, Job | None]:
    settings = settings or get_settings()
    settings.ensure_org_dirs(session.organization_id)

    if session.storage_backend == "s3":
        storage = _storage(settings)
        remote = storage.list_parts(
            session.object_key or "", session.storage_upload_id or ""
        )
        provided = {
            int(part["part_number"]): part
            for part in (parts or [])
            if part.get("etag")
        }
        stored = {
            int(part["part_number"]): part
            for part in (session.parts or [])
            if part.get("etag")
        }
        effective: dict[int, dict] = {}
        for number in range(1, session.total_parts + 1):
            part = provided.get(number) or stored.get(number)
            etag = remote.get(number) or (part or {}).get("etag")
            if not etag:
                continue
            effective[number] = {"part_number": number, "etag": etag}
        missing = [
            number
            for number in range(1, session.total_parts + 1)
            if number not in effective
        ]
        if missing:
            raise IncompleteUpload(missing)
        storage.complete_multipart(
            session.object_key or "",
            session.storage_upload_id or "",
            list(effective.values()),
        )
        session.storage_upload_id = None
        size = storage.head_size(session.object_key or "")
        if size != session.total_size:
            session.error = "tamanho do objeto não confere com o informado"
            db.commit()
            raise ValueError(session.error)
        temp_path = settings.uploads_tmp_dir / f"{session.id}-complete.tmp"
        storage.download(session.object_key or "", temp_path)
        try:
            digest = hashlib.sha256()
            with temp_path.open("rb") as handle:
                while data := handle.read(1024 * 1024):
                    digest.update(data)
            checksum = digest.hexdigest()
            existing = find_duplicate(db, session.organization_id, sha256=checksum)
            if existing is not None:
                storage.delete(session.object_key or "")
                _cleanup_session(db, session, settings)
                return existing, latest_job_for_video(
                    db, existing.id, session.organization_id
                )
            try:
                probe = probe_video(temp_path, settings)
            except FfmpegError:
                storage.delete(session.object_key or "")
                _cleanup_session(db, session, settings)
                raise
            video, job = _register_video(
                db, session, checksum=checksum, probe=probe, size_bytes=size, settings=settings
            )
        finally:
            temp_path.unlink(missing_ok=True)
        _cleanup_session(db, session, settings)
        return video, job

    missing = [
        number
        for number in range(1, session.total_parts + 1)
        if not _part_path(session, number, settings).exists()
        or _part_path(session, number, settings).stat().st_size
        != _expected_part_size(session, number)
    ]
    if missing:
        raise IncompleteUpload(missing)

    temp_path = settings.uploads_tmp_dir / f"{session.id}-complete.tmp"
    digest = hashlib.sha256()
    written = 0
    with temp_path.open("wb") as output:
        for number in range(1, session.total_parts + 1):
            part = _part_path(session, number, settings)
            with part.open("rb") as source:
                while data := source.read(1024 * 1024):
                    output.write(data)
                    digest.update(data)
                    written += len(data)
    if written != session.total_size:
        temp_path.unlink(missing_ok=True)
        raise ValueError("tamanho final não confere com o informado")

    checksum = digest.hexdigest()
    existing = find_duplicate(db, session.organization_id, sha256=checksum)
    if existing is not None:
        temp_path.unlink(missing_ok=True)
        _cleanup_session(db, session, settings)
        return existing, latest_job_for_video(db, existing.id, session.organization_id)

    try:
        probe = probe_video(temp_path, settings)
    except FfmpegError:
        temp_path.unlink(missing_ok=True)
        _cleanup_session(db, session, settings)
        raise

    final_path = settings.org_uploads_dir(session.organization_id) / (
        f"{session.id}-{safe_filename(session.filename)}"
    )
    temp_path.replace(final_path)
    video, job = _register_video(
        db,
        session,
        checksum=checksum,
        probe=probe,
        size_bytes=final_path.stat().st_size,
        settings=settings,
    )
    if video.id != session.id:
        final_path.unlink(missing_ok=True)
    _cleanup_session(db, session, settings)
    return video, job


def delete_session(
    db: Session, session: UploadSession, settings: Settings | None = None
) -> None:
    settings = settings or get_settings()
    _cleanup_session(db, session, settings)


def cleanup_stale_sessions(
    db: Session, settings: Settings | None = None, older_than_hours: int | None = None
) -> int:
    settings = settings or get_settings()
    hours = older_than_hours or settings.upload_session_ttl_hours
    cutoff = utcnow() - timedelta(hours=hours)
    count = 0
    for session in db.query(UploadSession).all():
        created = ensure_utc(session.created_at)
        if created is not None and created < cutoff:
            _cleanup_session(db, session, settings)
            count += 1
    return count
