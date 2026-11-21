from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import require_org
from ..config import get_settings
from ..db import get_db
from ..models import CameraProfile, Event, Video
from ..permissions import (
    EVENTS_VIEW,
    VIDEOS_ANALYZE,
    VIDEOS_MANAGE,
    VIDEOS_UPLOAD,
    VIDEOS_VIEW,
)
from ..schemas import (
    BulkDeleteRequest,
    BulkDeleteResult,
    BulkDeleteFailure,
    EventOut,
    ImportRequest,
    JobOut,
    ScanRequest,
    UploadResponse,
    VideoOut,
)
from ..services.ffmpeg import FfmpegError
from ..services.ingest import import_path, save_upload
from ..services.jobs import enqueue_video
from ..services.media import remote_media_response
from ..services.serializers import event_out, job_out, video_out
from ..storage import get_storage
from ..tenancy import AuthPrincipal, log_access, scoped_get, scoped_query
from ..services.video_deletion import VideoDeletionError, delete_one

router = APIRouter(prefix="/orgs/{slug}/videos", tags=["videos"])


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


def _allowed_import_root() -> Path:
    settings = get_settings()
    return settings.media_root.resolve()


def _validate_import_path(raw: str) -> Path:
    path = Path(raw).expanduser().resolve()
    root = _allowed_import_root()
    watch = get_settings().effective_watch_dir.resolve()
    if not (path == root or root in path.parents or path == watch or watch in path.parents):
        raise HTTPException(
            status_code=400,
            detail="importação permitida apenas dentro do diretório de mídia",
        )
    return path


@router.get("", response_model=list[VideoOut])
def list_videos(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: AuthPrincipal = Depends(require_org(VIDEOS_VIEW)),
    db: Session = Depends(get_db),
) -> list[VideoOut]:
    query = scoped_query(db, Video, principal.organization_id or "").order_by(
        Video.created_at.desc()
    )
    if status:
        query = query.filter(Video.status == status)
    videos = query.offset(offset).limit(limit).all()
    return [video_out(db, video) for video in videos]


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_video(
    request: Request,
    file: UploadFile = File(...),
    profile_id: str | None = Form(default=None),
    principal: AuthPrincipal = Depends(require_org(VIDEOS_UPLOAD)),
    db: Session = Depends(get_db),
) -> UploadResponse:
    organization_id = principal.organization_id or ""
    _profile_in_org(db, organization_id, profile_id)
    try:
        video, job = await save_upload(
            db,
            file,
            organization_id=organization_id,
            profile_id=profile_id,
            settings=get_settings(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FfmpegError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log_access(
        db,
        organization_id=organization_id,
        principal=principal,
        action="upload_video",
        resource_type="video",
        resource_id=video.id,
        request=request,
        commit=True,
    )
    return UploadResponse(
        video=video_out(db, video),
        job=job_out(job) if job else None,
    )


@router.post("/import", response_model=list[UploadResponse], status_code=201)
def import_videos(
    payload: ImportRequest,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(VIDEOS_UPLOAD)),
    db: Session = Depends(get_db),
) -> list[UploadResponse]:
    organization_id = principal.organization_id or ""
    _profile_in_org(db, organization_id, payload.profile_id)
    path = _validate_import_path(payload.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="caminho não encontrado")
    imported = import_path(
        db,
        path,
        organization_id=organization_id,
        profile_id=payload.profile_id,
        recursive=payload.recursive,
        settings=get_settings(),
    )
    for video, _job in imported:
        log_access(
            db,
            organization_id=organization_id,
            principal=principal,
            action="import_video",
            resource_type="video",
            resource_id=video.id,
            request=request,
        )
    db.commit()
    return [
        UploadResponse(
            video=video_out(db, video),
            job=job_out(job) if job else None,
        )
        for video, job in imported
    ]


@router.post("/scan", response_model=list[UploadResponse])
def scan_folder(
    request: Request,
    payload: ScanRequest | None = None,
    principal: AuthPrincipal = Depends(require_org(VIDEOS_UPLOAD)),
    db: Session = Depends(get_db),
) -> list[UploadResponse]:
    settings = get_settings()
    organization_id = principal.organization_id or ""
    _profile_in_org(db, organization_id, payload.profile_id if payload else None)
    root = (
        _validate_import_path(payload.path)
        if payload and payload.path
        else settings.effective_watch_dir.resolve()
    )
    if not root.exists():
        raise HTTPException(status_code=404, detail=f"pasta não encontrada: {root}")
    imported = import_path(
        db,
        root,
        organization_id=organization_id,
        profile_id=payload.profile_id if payload else None,
        recursive=payload.recursive if payload else True,
        settings=settings,
    )
    for video, _job in imported:
        log_access(
            db,
            organization_id=organization_id,
            principal=principal,
            action="scan_video",
            resource_type="video",
            resource_id=video.id,
            request=request,
        )
    db.commit()
    return [
        UploadResponse(
            video=video_out(db, video),
            job=job_out(job) if job else None,
        )
        for video, job in imported
    ]


@router.get("/{video_id}", response_model=VideoOut)
def get_video(
    video_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(VIDEOS_VIEW)),
    db: Session = Depends(get_db),
) -> VideoOut:
    video = scoped_get(db, Video, principal.organization_id or "", video_id, detail="vídeo não encontrado")
    log_access(
        db,
        organization_id=principal.organization_id or "",
        principal=principal,
        action="view_video",
        resource_type="video",
        resource_id=video.id,
        request=request,
        commit=True,
    )
    return video_out(db, video)


@router.post("/{video_id}/analyze", response_model=JobOut)
def analyze_video(
    video_id: str,
    principal: AuthPrincipal = Depends(require_org(VIDEOS_ANALYZE)),
    db: Session = Depends(get_db),
) -> JobOut:
    video = scoped_get(db, Video, principal.organization_id or "", video_id, detail="vídeo não encontrado")
    job = enqueue_video(db, video)
    return job_out(job)


@router.get("/{video_id}/events", response_model=list[EventOut])
def video_events(
    video_id: str,
    principal: AuthPrincipal = Depends(require_org(EVENTS_VIEW)),
    db: Session = Depends(get_db),
) -> list[EventOut]:
    video = scoped_get(db, Video, principal.organization_id or "", video_id, detail="vídeo não encontrado")
    events = (
        db.query(Event)
        .filter(
            Event.video_id == video.id,
            Event.organization_id == video.organization_id,
        )
        .order_by(Event.start_s.asc())
        .all()
    )
    return [event_out(event) for event in events]


@router.get("/{video_id}/stream")
def stream_video(
    video_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(VIDEOS_VIEW)),
    db: Session = Depends(get_db),
) -> FileResponse:
    video = scoped_get(db, Video, principal.organization_id or "", video_id, detail="vídeo não encontrado")
    if not video.proxy_path and not video.proxy_storage_key:
        raise HTTPException(status_code=404, detail="proxy ainda não disponível")
    log_access(
        db,
        organization_id=principal.organization_id or "",
        principal=principal,
        action="stream",
        resource_type="video",
        resource_id=video.id,
        request=request,
        commit=True,
    )
    if video.proxy_storage_key and video.storage_backend != "local":
        return remote_media_response(video.proxy_storage_key, "video/mp4")
    path = Path(video.proxy_path or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="proxy não encontrado no disco")
    return FileResponse(
        path, media_type="video/mp4", content_disposition_type="inline"
    )


@router.get("/{video_id}/thumbnail")
def video_thumbnail(
    video_id: str,
    principal: AuthPrincipal = Depends(require_org(VIDEOS_VIEW)),
    db: Session = Depends(get_db),
) -> FileResponse:
    video = scoped_get(db, Video, principal.organization_id or "", video_id, detail="vídeo não encontrado")
    if video.thumbnail_storage_key and video.storage_backend != "local":
        return remote_media_response(
            video.thumbnail_storage_key, "image/jpeg", headers={"Cache-Control": "no-cache"}
        )
    path = Path(video.thumbnail_path) if video.thumbnail_path else None
    if path is None or not path.exists():
        event = (
            db.query(Event)
            .filter(
                Event.video_id == video.id,
                Event.organization_id == video.organization_id,
                Event.thumbnail_path.isnot(None),
            )
            .order_by(Event.start_s.asc())
            .first()
        )
        path = Path(event.thumbnail_path) if event and event.thumbnail_path else None
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="thumbnail não disponível")
    return FileResponse(
        path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"}
    )


@router.post("/bulk-delete", response_model=BulkDeleteResult)
def bulk_delete_videos(
    payload: BulkDeleteRequest,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(VIDEOS_MANAGE)),
    db: Session = Depends(get_db),
) -> BulkDeleteResult:
    result = BulkDeleteResult()
    for video_id in dict.fromkeys(payload.ids):
        video = (
            db.query(Video)
            .filter(
                Video.id == video_id,
                Video.organization_id == principal.organization_id,
            )
            .one_or_none()
        )
        if video is None:
            result.failed.append(
                BulkDeleteFailure(
                    id=video_id, status=404, detail="vídeo não encontrado"
                )
            )
            continue
        try:
            delete_one(db, video, principal, request)
            result.deleted.append(video_id)
        except VideoDeletionError as exc:
            db.rollback()
            result.failed.append(
                BulkDeleteFailure(
                    id=video_id, status=exc.status_code, detail=exc.detail
                )
            )
        except Exception:  # noqa: BLE001 - per-item failure must not abort the batch
            db.rollback()
            result.failed.append(
                BulkDeleteFailure(
                    id=video_id, status=500, detail="falha inesperada ao excluir"
                )
            )
    return result


@router.delete("/{video_id}", status_code=204)
def delete_video(
    video_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(VIDEOS_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    video = scoped_get(
        db,
        Video,
        principal.organization_id or "",
        video_id,
        detail="vídeo não encontrado",
    )
    try:
        delete_one(db, video, principal, request)
    except VideoDeletionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
