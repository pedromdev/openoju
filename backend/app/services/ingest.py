from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

import aiofiles
from fastapi import UploadFile
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import Job, Video, new_id
from ..storage import StorageError, get_storage
from .ffmpeg import FfmpegError, probe_video
from .jobs import enqueue_video, latest_job_for_video

VIDEO_SUFFIXES = {".dav", ".mp4", ".avi", ".mkv", ".mov", ".m4v", ".ts", ".mts", ".m2ts"}


def safe_filename(name: str) -> str:
    base = Path(name or "video").name
    cleaned = "".join(c for c in base if c.isalnum() or c in ".-_ ").strip()
    cleaned = cleaned.replace(" ", "_")
    return cleaned[:180] or "video"


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_SUFFIXES


def list_video_files(root: Path, recursive: bool = True) -> list[Path]:
    if root.is_file():
        return [root] if is_video_file(root) else []
    if not root.exists():
        return []
    iterator: Iterable[Path] = root.rglob("*") if recursive else root.glob("*")
    result: list[Path] = []
    for path in iterator:
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if is_video_file(path):
            result.append(path)
    return sorted(result)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def find_duplicate(
    db: Session, organization_id: str, *, sha256: str | None = None, source_path: str | None = None
) -> Video | None:
    if sha256:
        found = (
            db.query(Video)
            .filter(Video.organization_id == organization_id, Video.sha256 == sha256)
            .one_or_none()
        )
        if found is not None:
            return found
    if source_path:
        return (
            db.query(Video)
            .filter(
                Video.organization_id == organization_id,
                Video.source_path == source_path,
            )
            .one_or_none()
        )
    return None


def create_video_from_path(
    db: Session,
    path: Path,
    *,
    organization_id: str,
    profile_id: str | None = None,
    sha256: str | None = None,
    settings: Settings | None = None,
) -> tuple[Video, Job | None]:
    settings = settings or get_settings()
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"arquivo não encontrado: {resolved}")
    if not is_video_file(resolved):
        raise ValueError(f"extensão não suportada: {resolved.suffix}")

    existing = find_duplicate(
        db, organization_id, sha256=sha256, source_path=str(resolved)
    )
    if existing is not None:
        return existing, latest_job_for_video(db, existing.id, organization_id)

    probe = probe_video(resolved, settings)
    video = Video(
        organization_id=organization_id,
        filename=resolved.name,
        source_path=str(resolved),
        storage_backend="local",
        sha256=sha256,
        size_bytes=resolved.stat().st_size,
        duration_s=probe.duration_s,
        fps=probe.fps,
        width=probe.width,
        height=probe.height,
        video_codec=probe.video_codec,
        audio_codec=probe.audio_codec,
        recorded_at=probe.recorded_at,
        status="uploaded",
        profile_id=profile_id,
    )
    db.add(video)
    db.commit()
    db.refresh(video)

    job: Job | None = None
    if settings.auto_analyze:
        job = enqueue_video(db, video)
    return video, job


async def save_upload(
    db: Session,
    upload: UploadFile,
    *,
    organization_id: str,
    profile_id: str | None = None,
    settings: Settings | None = None,
) -> tuple[Video, Job | None]:
    settings = settings or get_settings()
    settings.ensure_org_dirs(organization_id)
    original_name = safe_filename(upload.filename or "video.dav")
    suffix = Path(original_name).suffix.lower()
    if suffix not in VIDEO_SUFFIXES:
        raise ValueError(f"extensão não suportada: {suffix or 'sem extensão'}")
    token = new_id()
    destination = settings.org_uploads_dir(organization_id) / f"{token}-{original_name}"
    destination.parent.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    try:
        async with aiofiles.open(destination, "wb") as handle:
            while chunk := await upload.read(1024 * 1024):
                digest.update(chunk)
                await handle.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    checksum = digest.hexdigest()
    existing = find_duplicate(db, organization_id, sha256=checksum)
    if existing is not None:
        destination.unlink(missing_ok=True)
        return existing, latest_job_for_video(db, existing.id, organization_id)

    try:
        probe = probe_video(destination, settings)
    except FfmpegError:
        destination.unlink(missing_ok=True)
        raise

    backend = settings.storage_backend
    storage_key = settings.storage_key(organization_id, "videos", destination.name)
    if backend != "local":
        # Upload straight to object storage so the worker can read the file from
        # any node; the local copy is only scratch space.
        try:
            get_storage(settings).upload(destination, storage_key)
        except StorageError:
            destination.unlink(missing_ok=True)
            raise

    video = Video(
        id=token,
        organization_id=organization_id,
        filename=original_name,
        source_path=None if backend != "local" else str(destination.resolve()),
        storage_backend=backend,
        storage_key=storage_key,
        sha256=checksum,
        size_bytes=destination.stat().st_size,
        duration_s=probe.duration_s,
        fps=probe.fps,
        width=probe.width,
        height=probe.height,
        video_codec=probe.video_codec,
        audio_codec=probe.audio_codec,
        recorded_at=probe.recorded_at,
        status="uploaded",
        profile_id=profile_id,
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    if backend != "local":
        destination.unlink(missing_ok=True)

    job: Job | None = None
    if settings.auto_analyze:
        job = enqueue_video(db, video)
    return video, job


def import_path(
    db: Session,
    path: Path,
    *,
    organization_id: str,
    profile_id: str | None = None,
    recursive: bool = True,
    settings: Settings | None = None,
) -> list[tuple[Video, Job | None]]:
    settings = settings or get_settings()
    files = list_video_files(path.expanduser().resolve(), recursive=recursive)
    imported: list[tuple[Video, Job | None]] = []
    for file in files:
        try:
            imported.append(
                create_video_from_path(
                    db,
                    file,
                    organization_id=organization_id,
                    profile_id=profile_id,
                    settings=settings,
                )
            )
        except (FileNotFoundError, ValueError, FfmpegError, OSError):
            continue
    return imported


def remove_video_files(video: Video, settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    for raw in (video.proxy_path, video.thumbnail_path):
        if raw:
            Path(raw).unlink(missing_ok=True)
    # Uploaded originals live inside the managed org media root; imported
    # sources are user-owned and must never be deleted by the application.
    if not video.source_path:
        return
    try:
        source = Path(video.source_path).resolve()
        managed = settings.org_uploads_dir(video.organization_id).resolve()
        if managed in source.parents:
            source.unlink(missing_ok=True)
    except OSError:
        pass
