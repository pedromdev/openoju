from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Event, Job, Video
from ..schemas import EventOut, JobOut, VideoOut
from .jobs import latest_job_for_video


def job_out(job: Job) -> JobOut:
    return JobOut.model_validate(job)


def event_out(event: Event) -> EventOut:
    return EventOut.model_validate(event)


def video_out(db: Session, video: Video) -> VideoOut:
    count = (
        db.query(func.count(Event.id))
        .filter(
            Event.video_id == video.id,
            Event.organization_id == video.organization_id,
        )
        .scalar()
        or 0
    )
    job = latest_job_for_video(db, video.id, video.organization_id)
    payload = VideoOut.model_validate(video)
    return payload.model_copy(
        update={
            "event_count": int(count),
            "job_id": job.id if job else None,
            "job_status": job.status if job else None,
            "job_progress": job.progress if job else None,
            "job_stage": job.stage if job else None,
        }
    )
