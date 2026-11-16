from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import Request
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import Event, Job, LegalHold, Video, utcnow
from ..security import ensure_utc
from ..storage import StorageError, get_storage
from ..tenancy import AuthPrincipal, log_access, log_audit

ACTIVE_JOB_STATUSES = ("queued", "running")


class VideoDeletionError(RuntimeError):
    status_code = 409

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class VideoBusyError(VideoDeletionError):
    def __init__(self, job_id: str) -> None:
        super().__init__(
            f"vídeo com análise em andamento (job {job_id}); cancele e aguarde"
        )
        self.job_id = job_id


class LegalHoldError(VideoDeletionError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"vídeo sob legal hold: {reason}")


class ArtifactDeletionError(VideoDeletionError):
    status_code = 502


@dataclass
class DeletionArtifacts:
    local_paths: list[Path] = field(default_factory=list)
    storage_keys: list[str] = field(default_factory=list)


def active_job(db: Session, video_id: str) -> Job | None:
    return (
        db.query(Job)
        .filter(
            Job.video_id == video_id,
            (
                Job.status.in_(ACTIVE_JOB_STATUSES)
                | ((Job.status == "canceled") & (Job.finished_at.is_(None)))
            ),
        )
        .order_by(Job.created_at.desc())
        .first()
    )


def active_hold(
    db: Session, organization_id: str, video: Video, events: list[Event]
) -> LegalHold | None:
    resources = {("video", video.id)} | {("event", event.id) for event in events}
    holds = (
        db.query(LegalHold)
        .filter(
            LegalHold.organization_id == organization_id,
            LegalHold.resource_type.in_(["video", "event"]),
        )
        .all()
    )
    now = utcnow()
    for hold in holds:
        if (hold.resource_type, hold.resource_id) not in resources:
            continue
        expires = ensure_utc(hold.expires_at)
        if expires is None or expires > now:
            return hold
    return None


def collect_artifacts(
    video: Video, events: list[Event], settings: Settings
) -> DeletionArtifacts:
    artifacts = DeletionArtifacts()

    def add_path(raw: str | None) -> None:
        if not raw:
            return
        path = Path(raw)
        if path not in artifacts.local_paths:
            artifacts.local_paths.append(path)

    def add_key(key: str | None) -> None:
        if key and key not in artifacts.storage_keys:
            artifacts.storage_keys.append(key)

    add_key(video.storage_key)
    add_key(video.proxy_storage_key)
    add_key(video.thumbnail_storage_key)
    add_path(video.proxy_path)
    add_path(video.thumbnail_path)

    if video.source_path:
        try:
            source = Path(video.source_path).resolve()
            managed = settings.org_uploads_dir(video.organization_id).resolve()
            if managed in source.parents:
                add_path(video.source_path)
        except OSError:
            pass

    for event in events:
        add_key(event.clip_storage_key)
        add_key(event.thumbnail_storage_key)
        add_path(event.clip_path)
        add_path(event.thumbnail_path)
    return artifacts


def _delete_artifacts(artifacts: DeletionArtifacts, settings: Settings) -> None:
    if artifacts.storage_keys and settings.uses_object_storage:
        try:
            storage = get_storage(settings)
            for key in artifacts.storage_keys:
                storage.delete(key, strict=True)
        except StorageError as exc:
            raise ArtifactDeletionError(
                f"falha ao excluir mídia do storage; nada foi removido do banco: {exc}"
            ) from exc
    for path in artifacts.local_paths:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise ArtifactDeletionError(f"falha ao excluir arquivo {path}: {exc}") from exc


def _remove_job_dirs(db: Session, video_id: str, settings: Settings) -> None:
    for (job_id,) in db.query(Job.id).filter(Job.video_id == video_id).all():
        shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)


def delete_one(
    db: Session,
    video: Video,
    principal: AuthPrincipal,
    request: Request | None,
    settings: Settings | None = None,
) -> None:
    settings = settings or get_settings()
    busy = active_job(db, video.id)
    if busy is not None:
        raise VideoBusyError(busy.id)

    events = (
        db.query(Event)
        .filter(
            Event.video_id == video.id,
            Event.organization_id == video.organization_id,
        )
        .all()
    )
    hold = active_hold(db, video.organization_id, video, events)
    if hold is not None:
        raise LegalHoldError(hold.reason)

    artifacts = collect_artifacts(video, events, settings)
    filename = video.filename
    size_bytes = video.size_bytes
    event_count = len(events)
    job_ids = [row[0] for row in db.query(Job.id).filter(Job.video_id == video.id).all()]

    _delete_artifacts(artifacts, settings)

    log_audit(
        db,
        organization_id=video.organization_id,
        actor_user_id=principal.user_id,
        actor_api_key_id=principal.api_key.id if principal.api_key else None,
        action="video.delete",
        resource_type="video",
        resource_id=video.id,
        metadata={
            "filename": filename,
            "size_bytes": size_bytes,
            "event_count": event_count,
            "local_files": len(artifacts.local_paths),
            "storage_objects": len(artifacts.storage_keys),
        },
        request=request,
    )
    log_access(
        db,
        organization_id=video.organization_id,
        principal=principal,
        action="delete_video",
        resource_type="video",
        resource_id=video.id,
        request=request,
    )
    db.delete(video)
    db.commit()

    for job_id in job_ids:
        shutil.rmtree(settings.jobs_dir / job_id, ignore_errors=True)
