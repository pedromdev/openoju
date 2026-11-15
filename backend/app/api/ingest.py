from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..auth import require_api_key
from ..config import get_settings
from ..db import get_db
from ..models import CameraProfile, IngestBatch, UploadSession
from ..schemas import (
    BatchCreate,
    BatchOut,
    IngestCompleteOut,
    IngestCompleteRequest,
    IngestUploadCreate,
    IngestUploadOut,
    UploadPartOut,
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
from ..tenancy import AuthPrincipal, log_audit, scoped_get

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _batch(db: Session, organization_id: str, batch_id: str | None) -> IngestBatch | None:
    if batch_id is None:
        return None
    return scoped_get(
        db, IngestBatch, organization_id, batch_id, detail="lote não encontrado"
    )


def _profile(db: Session, organization_id: str, profile_id: str | None) -> None:
    if profile_id is None:
        return
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


def _scoped_upload(
    db: Session, organization_id: str, upload_id: str
) -> UploadSession:
    upload = (
        db.query(UploadSession)
        .filter(
            UploadSession.id == upload_id,
            UploadSession.organization_id == organization_id,
        )
        .one_or_none()
    )
    if upload is None:
        raise HTTPException(status_code=404, detail="upload não encontrado")
    return upload


@router.post("/batches", response_model=BatchOut, status_code=201)
def create_batch(
    payload: BatchCreate,
    principal: AuthPrincipal = Depends(require_api_key("ingest:write")),
    db: Session = Depends(get_db),
) -> BatchOut:
    batch = IngestBatch(
        organization_id=principal.organization_id or "",
        name=payload.name,
        status="uploading",
        api_key_id=principal.api_key.id if principal.api_key else None,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_api_key_id=batch.api_key_id,
        action="ingest_batch.create",
        resource_type="ingest_batch",
        resource_id=batch.id,
        metadata={"name": batch.name},
        commit=True,
    )
    return BatchOut.model_validate(batch)


@router.get("/batches/{batch_id}", response_model=BatchOut)
def get_batch(
    batch_id: str,
    principal: AuthPrincipal = Depends(require_api_key("ingest:write")),
    db: Session = Depends(get_db),
) -> BatchOut:
    batch = scoped_get(
        db,
        IngestBatch,
        principal.organization_id or "",
        batch_id,
        detail="lote não encontrado",
    )
    return BatchOut.model_validate(batch)


@router.post("/uploads", response_model=IngestUploadOut, status_code=201)
def create_ingest_upload(
    payload: IngestUploadCreate,
    principal: AuthPrincipal = Depends(require_api_key("ingest:write")),
    db: Session = Depends(get_db),
) -> IngestUploadOut:
    organization_id = principal.organization_id or ""
    _profile(db, organization_id, payload.profile_id)
    _batch(db, organization_id, payload.batch_id)
    try:
        upload = create_session(
            db,
            organization_id=organization_id,
            filename=payload.filename,
            size=payload.size,
            profile_id=payload.profile_id,
            batch_id=payload.batch_id,
            settings=get_settings(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=507, detail=str(exc)) from exc
    return IngestUploadOut(
        upload_id=upload.id,
        part_size=upload.part_size,
        total_parts=upload.total_parts,
        received_parts=[],
        upload_url_template=(
            f"/api/v1/ingest/uploads/{upload.id}/parts/{{part_number}}"
        ),
        storage_backend=upload.storage_backend,
        part_urls=part_urls(upload),
    )


@router.get("/uploads/{upload_id}", response_model=IngestUploadOut)
def get_ingest_upload(
    upload_id: str,
    principal: AuthPrincipal = Depends(require_api_key("ingest:write")),
    db: Session = Depends(get_db),
) -> IngestUploadOut:
    upload = _scoped_upload(db, principal.organization_id or "", upload_id)
    return IngestUploadOut(
        upload_id=upload.id,
        part_size=upload.part_size,
        total_parts=upload.total_parts,
        received_parts=received_parts(upload, get_settings()),
        upload_url_template=(
            f"/api/v1/ingest/uploads/{upload.id}/parts/{{part_number}}"
        ),
        storage_backend=upload.storage_backend,
        part_urls=part_urls(upload),
    )


@router.put("/uploads/{upload_id}/parts/{part_number}", response_model=UploadPartOut)
async def upload_ingest_part(
    upload_id: str,
    part_number: int,
    request: Request,
    principal: AuthPrincipal = Depends(require_api_key("ingest:write")),
    db: Session = Depends(get_db),
) -> UploadPartOut:
    upload = _scoped_upload(db, principal.organization_id or "", upload_id)
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > upload.part_size:
        raise HTTPException(status_code=413, detail="parte maior que o tamanho permitido")
    data = await request.body()
    try:
        received = save_part(db, upload, part_number, data, get_settings())
    except (IndexError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    etag = next(
        (
            part.get("etag")
            for part in (upload.parts or [])
            if int(part.get("part_number", 0)) == part_number
        ),
        None,
    )
    return UploadPartOut(
        upload_id=upload.id,
        received=received,
        total_parts=upload.total_parts,
        complete=received == upload.total_parts,
        etag=etag,
    )


@router.post("/uploads/{upload_id}/complete", response_model=IngestCompleteOut)
def complete_ingest_upload(
    upload_id: str,
    request: Request,
    payload: IngestCompleteRequest | None = None,
    principal: AuthPrincipal = Depends(require_api_key("ingest:write")),
    db: Session = Depends(get_db),
) -> IngestCompleteOut:
    upload = _scoped_upload(db, principal.organization_id or "", upload_id)
    organization_id = upload.organization_id
    batch_id = upload.batch_id
    try:
        video, job = complete_session(
            db,
            upload,
            get_settings(),
            parts=[part.model_dump() for part in payload.parts] if payload and payload.parts else None,
        )
    except IncompleteUpload as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FfmpegError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if batch_id:
        batch = db.get(IngestBatch, batch_id)
        if batch is not None:
            remaining = (
                db.query(UploadSession)
                .filter(
                    UploadSession.batch_id == batch_id,
                    UploadSession.organization_id == organization_id,
                )
                .count()
            )
            batch.status = "uploading" if remaining else "completed"
            db.commit()
    log_audit(
        db,
        organization_id=organization_id,
        actor_api_key_id=principal.api_key.id if principal.api_key else None,
        action="ingest.complete",
        resource_type="video",
        resource_id=video.id,
        request=request,
        commit=True,
    )
    return IngestCompleteOut(
        video=video_out(db, video),
        job=job_out(job) if job else None,
    )


@router.delete("/uploads/{upload_id}", status_code=204)
def abandon_ingest_upload(
    upload_id: str,
    principal: AuthPrincipal = Depends(require_api_key("ingest:write")),
    db: Session = Depends(get_db),
) -> None:
    upload = _scoped_upload(db, principal.organization_id or "", upload_id)
    delete_session(db, upload, get_settings())
