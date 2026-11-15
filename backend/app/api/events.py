from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth import require_org
from ..db import get_db
from ..models import Event
from ..permissions import EVENTS_REVIEW, EVENTS_VIEW
from ..schemas import EventOut, ReviewUpdate
from ..services.serializers import event_out
from ..tenancy import AuthPrincipal, log_access, scoped_get
from ..storage import get_storage

router = APIRouter(prefix="/orgs/{slug}/events", tags=["events"])


@router.get("/{event_id}", response_model=EventOut)
def get_event(
    event_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(EVENTS_VIEW)),
    db: Session = Depends(get_db),
) -> EventOut:
    event = scoped_get(
        db, Event, principal.organization_id or "", event_id, detail="evento não encontrado"
    )
    log_access(
        db,
        organization_id=event.organization_id,
        principal=principal,
        action="view_event",
        resource_type="event",
        resource_id=event.id,
        request=request,
        commit=True,
    )
    return event_out(event)


@router.patch("/{event_id}", response_model=EventOut)
def review_event(
    event_id: str,
    payload: ReviewUpdate,
    principal: AuthPrincipal = Depends(require_org(EVENTS_REVIEW)),
    db: Session = Depends(get_db),
) -> EventOut:
    event = scoped_get(
        db, Event, principal.organization_id or "", event_id, detail="evento não encontrado"
    )
    event.review_status = payload.review_status
    if payload.notes is not None:
        event.notes = payload.notes
    db.commit()
    db.refresh(event)
    return event_out(event)


@router.get("/{event_id}/thumbnail")
def event_thumbnail(
    event_id: str,
    principal: AuthPrincipal = Depends(require_org(EVENTS_VIEW)),
    db: Session = Depends(get_db),
) -> FileResponse:
    event = scoped_get(
        db, Event, principal.organization_id or "", event_id, detail="evento não encontrado"
    )
    if event.thumbnail_storage_key:
        return RedirectResponse(get_storage().presign_get(event.thumbnail_storage_key), status_code=302)
    if not event.thumbnail_path:
        raise HTTPException(status_code=404, detail="thumbnail não disponível")
    path = Path(event.thumbnail_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="thumbnail não encontrada")
    return FileResponse(
        path, media_type="image/jpeg", headers={"Cache-Control": "no-cache"}
    )


@router.get("/{event_id}/clip")
def event_clip(
    event_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(EVENTS_VIEW)),
    db: Session = Depends(get_db),
) -> FileResponse:
    event = scoped_get(
        db, Event, principal.organization_id or "", event_id, detail="evento não encontrado"
    )
    if not event.clip_path and not event.clip_storage_key:
        raise HTTPException(status_code=404, detail="clipe não disponível")
    if event.clip_storage_key:
        log_access(
            db,
            organization_id=event.organization_id,
            principal=principal,
            action="download_clip",
            resource_type="event",
            resource_id=event.id,
            request=request,
            commit=True,
        )
        return RedirectResponse(get_storage().presign_get(event.clip_storage_key), status_code=302)
    path = Path(event.clip_path or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="clipe não encontrado")
    log_access(
        db,
        organization_id=event.organization_id,
        principal=principal,
        action="download_clip",
        resource_type="event",
        resource_id=event.id,
        request=request,
        commit=True,
    )
    return FileResponse(path, media_type="video/mp4", content_disposition_type="inline")
