from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..models import (
    AccessLog,
    AuditLog,
    Event,
    Job,
    LegalHold,
    LoginAttempt,
    PrivacySettings,
    Session as AuthSession,
    Video,
    WebhookDelivery,
    utcnow,
)
from ..security import ensure_utc
from ..storage import get_storage

EXPIRED_STATUS = "expired"


def _months_ago(now: datetime, months: int) -> datetime:
    return now - timedelta(days=30 * months)


def _active_holds(db: Session, organization_id: str, now: datetime) -> set[tuple[str, str]]:
    holds = (
        db.query(LegalHold)
        .filter(LegalHold.organization_id == organization_id)
        .all()
    )
    active: set[tuple[str, str]] = set()
    for hold in holds:
        expires = ensure_utc(hold.expires_at)
        if expires is None or expires > now:
            active.add((hold.resource_type, hold.resource_id))
    return active


def _delete_video_media(db: Session, video: Video, settings: Settings) -> int:
    storage = get_storage(settings) if settings.uses_object_storage else None
    removed = 0
    for raw in (video.source_path, video.proxy_path, video.thumbnail_path):
        if raw:
            Path(raw).unlink(missing_ok=True)
            removed += 1
    for key in (video.storage_key, video.proxy_storage_key, video.thumbnail_storage_key):
        if key and storage is not None:
            storage.delete(key)
            removed += 1
    video.source_path = None
    video.proxy_path = None
    video.thumbnail_path = None
    video.storage_key = None
    video.proxy_storage_key = None
    video.thumbnail_storage_key = None
    video.status = EXPIRED_STATUS
    return removed


def _delete_event_media(db: Session, event: Event, settings: Settings) -> int:
    storage = get_storage(settings) if settings.uses_object_storage else None
    removed = 0
    for raw in (event.thumbnail_path, event.clip_path):
        if raw:
            Path(raw).unlink(missing_ok=True)
            removed += 1
    for key in (event.thumbnail_storage_key, event.clip_storage_key):
        if key and storage is not None:
            storage.delete(key)
            removed += 1
    event.thumbnail_path = None
    event.clip_path = None
    event.thumbnail_storage_key = None
    event.clip_storage_key = None
    return removed


def run_retention(
    db: Session,
    settings: Settings | None = None,
    *,
    organization_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    settings = settings or get_settings()
    now = now or utcnow()
    counts = {
        "videos_expired": 0,
        "events_expired": 0,
        "events_deleted": 0,
        "access_logs": 0,
        "audit_logs": 0,
        "sessions": 0,
        "webhook_deliveries": 0,
        "job_logs": 0,
        "login_attempts": 0,
        "files_removed": 0,
    }

    settings_query = db.query(PrivacySettings)
    if organization_id:
        settings_query = settings_query.filter(
            PrivacySettings.organization_id == organization_id
        )
    privacy_rows = settings_query.all()
    org_ids = (
        [organization_id]
        if organization_id
        else [row.organization_id for row in privacy_rows]
    )

    for org_id in org_ids:
        privacy = next(
            (row for row in privacy_rows if row.organization_id == org_id), None
        )
        media_days = privacy.retention_media_days if privacy else 30
        event_months = privacy.retention_event_months if privacy else 12
        access_months = privacy.retention_access_logs_months if privacy else 6
        audit_months = privacy.retention_audit_months if privacy else 12
        holds = _active_holds(db, org_id, now)

        media_cutoff = now - timedelta(days=media_days)
        videos = (
            db.query(Video)
            .filter(
                Video.organization_id == org_id,
                Video.created_at < media_cutoff,
                Video.status != EXPIRED_STATUS,
            )
            .all()
        )
        expired_video_ids: set[str] = set()
        for video in videos:
            if ("video", video.id) in holds:
                continue
            counts["files_removed"] += _delete_video_media(db, video, settings)
            expired_video_ids.add(video.id)
            counts["videos_expired"] += 1

        event_cutoff = _months_ago(now, event_months)
        events = (
            db.query(Event)
            .filter(
                Event.organization_id == org_id,
                Event.created_at < event_cutoff,
            )
            .all()
        )
        for event in events:
            if ("event", event.id) in holds:
                continue
            counts["files_removed"] += _delete_event_media(db, event, settings)
            db.delete(event)
            counts["events_deleted"] += 1

        media_events = (
            db.query(Event)
            .filter(
                Event.organization_id == org_id,
                Event.video_id.in_(expired_video_ids),
            )
            .all()
            if expired_video_ids
            else []
        )
        for event in media_events:
            if ("event", event.id) in holds:
                continue
            if event.clip_path or event.thumbnail_path or event.clip_storage_key or event.thumbnail_storage_key:
                counts["files_removed"] += _delete_event_media(db, event, settings)
                counts["events_expired"] += 1

        access_cutoff = _months_ago(now, access_months)
        counts["access_logs"] += (
            db.query(AccessLog)
            .filter(AccessLog.organization_id == org_id, AccessLog.created_at < access_cutoff)
            .delete(synchronize_session=False)
        )
        audit_cutoff = _months_ago(now, audit_months)
        counts["audit_logs"] += (
            db.query(AuditLog)
            .filter(AuditLog.organization_id == org_id, AuditLog.created_at < audit_cutoff)
            .delete(synchronize_session=False)
        )

    session_cutoff = now - timedelta(days=settings.retention_session_days)
    counts["sessions"] += (
        db.query(AuthSession)
        .filter(AuthSession.expires_at < session_cutoff)
        .delete(synchronize_session=False)
    )
    webhook_cutoff = now - timedelta(days=settings.retention_webhook_days)
    counts["webhook_deliveries"] += (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.created_at < webhook_cutoff)
        .delete(synchronize_session=False)
    )

    job_log_cutoff = now - timedelta(days=settings.retention_media_days)
    stale_jobs = (
        db.query(Job)
        .filter(
            Job.finished_at.isnot(None),
            Job.finished_at < job_log_cutoff,
            ((Job.log_key.isnot(None)) | (Job.log_path.isnot(None))),
        )
        .all()
    )
    storage = get_storage(settings) if settings.uses_object_storage else None
    for job in stale_jobs:
        if storage is not None and job.log_key:
            storage.delete(job.log_key)
            counts["job_logs"] += 1
        if job.log_path:
            shutil.rmtree(Path(job.log_path).parent, ignore_errors=True)
        job.log_key = None
        job.log_path = None

    attempt_cutoff = now - timedelta(days=1)
    counts["login_attempts"] += (
        db.query(LoginAttempt)
        .filter(LoginAttempt.occurred_at < attempt_cutoff)
        .delete(synchronize_session=False)
    )

    from .uploads import cleanup_stale_sessions

    counts["sessions"] += cleanup_stale_sessions(db, settings)
    db.commit()
    return counts
