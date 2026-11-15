from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..auth import require_org
from ..db import SessionLocal, get_db
from ..models import Job
from ..permissions import JOBS_CANCEL, JOBS_VIEW
from ..schemas import JobOut
from ..services.jobs import cancel_job, job_payload
from ..services.serializers import job_out
from ..tenancy import AuthPrincipal, scoped_get, scoped_query

router = APIRouter(prefix="/orgs/{slug}/jobs", tags=["jobs"])


@router.get("", response_model=list[JobOut])
def list_jobs(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthPrincipal = Depends(require_org(JOBS_VIEW)),
    db: Session = Depends(get_db),
) -> list[JobOut]:
    query = scoped_query(db, Job, principal.organization_id or "").order_by(
        Job.created_at.desc()
    )
    if status:
        query = query.filter(Job.status == status)
    return [job_out(job) for job in query.limit(limit).all()]


@router.get("/{job_id}", response_model=JobOut)
def get_job(
    job_id: str,
    principal: AuthPrincipal = Depends(require_org(JOBS_VIEW)),
    db: Session = Depends(get_db),
) -> JobOut:
    job = scoped_get(db, Job, principal.organization_id or "", job_id, detail="job não encontrado")
    return job_out(job)


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel(
    job_id: str,
    principal: AuthPrincipal = Depends(require_org(JOBS_CANCEL)),
    db: Session = Depends(get_db),
) -> JobOut:
    job = scoped_get(db, Job, principal.organization_id or "", job_id, detail="job não encontrado")
    return job_out(cancel_job(db, job))


@router.get("/{job_id}/log")
def job_log(
    job_id: str,
    principal: AuthPrincipal = Depends(require_org(JOBS_VIEW)),
    db: Session = Depends(get_db),
) -> FileResponse:
    job = scoped_get(db, Job, principal.organization_id or "", job_id, detail="job não encontrado")
    if not job.log_path:
        raise HTTPException(status_code=404, detail="log ainda não disponível")
    path = Path(job.log_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="log não encontrado")
    return FileResponse(path, media_type="text/plain")


@router.get("/{job_id}/events")
async def job_events(
    job_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(JOBS_VIEW)),
    db: Session = Depends(get_db),
):
    organization_id = principal.organization_id or ""
    scoped_get(db, Job, organization_id, job_id, detail="job não encontrado")

    async def generator():
        last: str | None = None
        while True:
            if await request.is_disconnected():
                break
            session = SessionLocal()
            try:
                current = (
                    session.query(Job)
                    .filter(
                        Job.id == job_id,
                        Job.organization_id == organization_id,
                    )
                    .one_or_none()
                )
                if current is None:
                    break
                payload = job_payload(current)
            finally:
                session.close()
            serialized = json.dumps(payload, ensure_ascii=False)
            if serialized != last:
                yield f"data: {serialized}\n\n"
                last = serialized
            if payload["status"] in {"completed", "failed", "canceled"}:
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
