from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import require_org
from ..config import get_settings
from ..db import get_db
from ..models import CameraProfile, UploadSession
from ..permissions import VIDEOS_UPLOAD
from ..schemas import (
    IngestCompleteRequest,
    UploadInitOut,
    UploadInitRequest,
    UploadPartOut,
    UploadResponse,
    UploadSessionOut,
)
from ..services.ffmpeg import FfmpegError
from ..services.serializers import job_out, video_out
from ..services.uploads import (
    IncompleteUpload,
    complete_session,
    create_session,
    delete_session,
    part_urls,
    received_parts,
    save_part,
)
from ..tenancy import AuthPrincipal, log_access

router = APIRouter(prefix="/orgs/{slug}/uploads", tags=["uploads"])


def scoped_upload(
    db: Session, organization_id: str, upload_id: str
) -> UploadSession:
    session = (
        db.query(UploadSession)
        .filter(
            UploadSession.id == upload_id,
            UploadSession.organization_id == organization_id,
        )
        .one_or_none()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="upload não encontrado")
    return session


def _profile_in_org(
    db: Session, organization_id: str, profile_id: str | None
) -> str | None:
    if profile_id is None:
        return None
    profile = (
        db.query(CameraProfile)
        .filter(
            CameraProfile.id == profile_id,
            CameraProfile.organization_id == organization_id,
        )
        .one_or_none()
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="perfil não encontrado")
    return profile.id


@router.post("/init", response_model=UploadInitOut, status_code=201)
def init_upload(
    payload: UploadInitRequest,
    principal: AuthPrincipal = Depends(require_org(VIDEOS_UPLOAD)),
    db: Session = Depends(get_db),
) -> UploadInitOut:
    organization_id = principal.organization_id or ""
    _profile_in_org(db, organization_id, payload.profile_id)
    try:
        session = create_session(
            db,
            organization_id=organization_id,
            filename=payload.filename,
            size=payload.size,
            profile_id=payload.profile_id,
            settings=get_settings(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc
    return UploadInitOut(
        upload_id=session.id,
        filename=session.filename,
        part_size=session.part_size,
        total_parts=session.total_parts,
        received_parts=[],
        storage_backend=session.storage_backend,
        part_urls=part_urls(session),
    )


@router.get("/{upload_id}", response_model=UploadSessionOut)
def get_upload(
    upload_id: str,
    principal: AuthPrincipal = Depends(require_org(VIDEOS_UPLOAD)),
    db: Session = Depends(get_db),
) -> UploadSessionOut:
    session = scoped_upload(db, principal.organization_id or "", upload_id)
    return UploadSessionOut(
        upload_id=session.id,
        filename=session.filename,
        part_size=session.part_size,
        total_parts=session.total_parts,
        received_parts=received_parts(session, get_settings()),
        storage_backend=session.storage_backend,
        part_urls=part_urls(session),
        status=session.status,
        error=session.error,
        created_at=session.created_at,
    )


@router.put("/{upload_id}/parts/{part_number}", response_model=UploadPartOut)
async def upload_part(
    upload_id: str,
    part_number: int,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(VIDEOS_UPLOAD)),
    db: Session = Depends(get_db),
) -> UploadPartOut:
    session = scoped_upload(db, principal.organization_id or "", upload_id)
    settings = get_settings()
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > session.part_size:
        raise HTTPException(status_code=413, detail="parte maior que o tamanho permitido")
    data = await request.body()
    try:
        received = save_part(db, session, part_number, data, settings)
    except (IndexError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    etag = next(
        (
            part.get("etag")
            for part in (session.parts or [])
            if int(part.get("part_number", 0)) == part_number
        ),
        None,
    )
    return UploadPartOut(
        upload_id=session.id,
        received=received,
        total_parts=session.total_parts,
        complete=received == session.total_parts,
        etag=etag,
    )


@router.post("/{upload_id}/complete", response_model=UploadResponse)
def complete_upload(
    upload_id: str,
    request: Request,
    payload: IngestCompleteRequest | None = None,
    principal: AuthPrincipal = Depends(require_org(VIDEOS_UPLOAD)),
    db: Session = Depends(get_db),
) -> UploadResponse:
    session = scoped_upload(db, principal.organization_id or "", upload_id)
    organization_id = session.organization_id
    try:
        video, job = complete_session(
            db,
            session,
            get_settings(),
            parts=[part.model_dump() for part in payload.parts] if payload and payload.parts else None,
        )
    except IncompleteUpload as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FfmpegError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_access(
        db,
        organization_id=organization_id,
        principal=principal,
        action="complete_upload",
        resource_type="video",
        resource_id=video.id,
        request=request,
        commit=True,
    )
    return UploadResponse(
        video=video_out(db, video),
        job=job_out(job) if job else None,
    )


@router.delete("/{upload_id}", status_code=204)
def abandon_upload(
    upload_id: str,
    principal: AuthPrincipal = Depends(require_org(VIDEOS_UPLOAD)),
    db: Session = Depends(get_db),
) -> None:
    session = scoped_upload(db, principal.organization_id or "", upload_id)
    delete_session(db, session, get_settings())
