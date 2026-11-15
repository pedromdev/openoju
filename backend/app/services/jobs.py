from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Job, Video, utcnow
from ..security import ensure_utc

ACTIVE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = ("completed", "failed", "canceled")


def active_job_for_video(
    db: Session, video_id: str, organization_id: str | None = None
) -> Job | None:
    query = db.query(Job).filter(
        Job.video_id == video_id, Job.status.in_(ACTIVE_STATUSES)
    )
    if organization_id is not None:
        query = query.filter(Job.organization_id == organization_id)
    return query.order_by(Job.created_at.desc()).first()


def latest_job_for_video(
    db: Session, video_id: str, organization_id: str | None = None
) -> Job | None:
    query = db.query(Job).filter(Job.video_id == video_id)
    if organization_id is not None:
        query = query.filter(Job.organization_id == organization_id)
    return query.order_by(Job.created_at.desc()).first()


def enqueue_video(db: Session, video: Video) -> Job:
    active = active_job_for_video(db, video.id, video.organization_id)
    if active is not None:
        return active
    job = Job(
        organization_id=video.organization_id,
        video_id=video.id,
        status="queued",
        stage="queued",
    )
    db.add(job)
    video.status = "queued"
    video.error = None
    db.commit()
    db.refresh(job)
    return job


def claim_next_job(db: Session, worker_id: str) -> Job | None:
    now = utcnow()
    settings = get_settings()
    if settings.is_sqlite:
        statement = text(
            """
            UPDATE jobs
               SET status = 'running',
                   stage = 'starting',
                   started_at = :now,
                   heartbeat_at = :now,
                   worker_id = :worker
             WHERE id = (
                   SELECT id FROM jobs
                    WHERE status = 'queued'
                    ORDER BY created_at ASC
                    LIMIT 1
             )
         RETURNING id
            """
        )
    else:
        statement = text(
            """
            UPDATE jobs
               SET status = 'running',
                   stage = 'starting',
                   started_at = :now,
                   heartbeat_at = :now,
                   worker_id = :worker
             WHERE id = (
                   SELECT id FROM jobs
                    WHERE status = 'queued'
                    ORDER BY created_at ASC
                      FOR UPDATE SKIP LOCKED
                    LIMIT 1
             )
         RETURNING id
            """
        )
    row = db.execute(statement, {"now": now, "worker": worker_id}).first()
    db.commit()
    if row is None:
        return None
    job = db.get(Job, row[0])
    if job is not None:
        video = db.get(Video, job.video_id)
        if video is not None:
            video.status = "analyzing"
            db.commit()
    return job


def update_job(db: Session, job_id: str, **fields: object) -> Job | None:
    job = db.get(Job, job_id)
    if job is None:
        return None
    allowed = {
        "status",
        "stage",
        "progress",
        "message",
        "error",
        "result_path",
        "log_path",
        "worker_id",
        "started_at",
        "finished_at",
        "heartbeat_at",
    }
    for key, value in fields.items():
        if key in allowed:
            setattr(job, key, value)
    if fields:
        db.add(job)
        db.commit()
        db.refresh(job)
    return job


def progress(
    db: Session,
    job_id: str,
    *,
    stage: str | None = None,
    value: float | None = None,
    message: str | None = None,
) -> Job | None:
    fields: dict[str, object] = {"heartbeat_at": utcnow()}
    if stage is not None:
        fields["stage"] = stage
    if value is not None:
        fields["progress"] = max(0.0, min(1.0, float(value)))
    if message is not None:
        fields["message"] = message[:2000]
    return update_job(db, job_id, **fields)


def finish_job(
    db: Session,
    job_id: str,
    *,
    status: str,
    message: str | None = None,
    error: str | None = None,
    result_path: str | None = None,
) -> Job | None:
    fields: dict[str, object] = {
        "status": status,
        "finished_at": utcnow(),
        "heartbeat_at": utcnow(),
    }
    if message is not None:
        fields["message"] = message[:2000]
    if error is not None:
        fields["error"] = error[:8000]
    if result_path is not None:
        fields["result_path"] = result_path
    if status == "completed":
        fields["progress"] = 1.0
        fields["stage"] = "completed"
    elif status == "failed":
        fields["stage"] = "failed"
    elif status == "canceled":
        fields["stage"] = "canceled"
    return update_job(db, job_id, **fields)


def cancel_job(db: Session, job: Job) -> Job:
    if job.status == "queued":
        job.status = "canceled"
        job.stage = "canceled"
        job.finished_at = utcnow()
        video = db.get(Video, job.video_id)
        if video is not None:
            video.status = "uploaded"
        db.commit()
        db.refresh(job)
    elif job.status == "running":
        # The worker observes this flag and terminates the child process.
        job.status = "canceled"
        job.message = "cancelamento solicitado"
        job.heartbeat_at = utcnow()
        db.commit()
        db.refresh(job)
    return job


def reset_stale_jobs(db: Session, stale_after_s: int = 15 * 60) -> int:
    cutoff = utcnow() - timedelta(seconds=stale_after_s)
    count = 0
    for job in db.query(Job).filter(Job.status == "running").all():
        heartbeat = ensure_utc(job.heartbeat_at)
        if heartbeat is None or heartbeat < cutoff:
            job.status = "failed"
            job.stage = "failed"
            job.error = "job órfão: worker interrompido"
            job.finished_at = utcnow()
            video = db.get(Video, job.video_id)
            if video is not None and video.status == "analyzing":
                video.status = "failed"
                video.error = job.error
            count += 1
    db.commit()
    return count


def job_payload(job: Job) -> dict[str, object]:
    return {
        "id": job.id,
        "video_id": job.video_id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def job_is_canceled(db: Session, job_id: str) -> bool:
    db.expire_all()
    job = db.get(Job, job_id)
    return job is not None and job.status == "canceled"
