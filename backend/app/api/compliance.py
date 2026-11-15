from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..auth import require_org
from ..config import get_settings
from ..db import get_db
from ..models import (
    CameraProfile,
    DataSubjectRequest,
    Event,
    LegalHold,
    Membership,
    Organization,
    PrivacySettings,
    Video,
    utcnow,
)
from ..permissions import DSR_MANAGE, PRIVACY_MANAGE
from ..schemas import (
    DsrCreate,
    DsrOut,
    DsrUpdate,
    LegalHoldIn,
    LegalHoldOut,
    PrivacySettingsIn,
    PrivacySettingsOut,
    PublicPrivacyOut,
)
from ..security import ensure_utc, login_limiter
from ..services.organizations import generate_protocol
from ..services.retention import run_retention
from ..storage import get_storage
from ..tenancy import AuthPrincipal, client_ip, log_audit, organization_by_slug, scoped_get

router = APIRouter(tags=["compliance"])


def _privacy(db: Session, organization_id: str) -> PrivacySettings:
    privacy = db.get(PrivacySettings, organization_id)
    if privacy is None:
        privacy = PrivacySettings(organization_id=organization_id)
        db.add(privacy)
        db.commit()
        db.refresh(privacy)
    return privacy


def _public_payload(organization: Organization, privacy: PrivacySettings) -> PublicPrivacyOut:
    return PublicPrivacyOut(
        organization_name=organization.name,
        organization_slug=organization.slug,
        legal_basis=privacy.legal_basis,
        retention_media_days=privacy.retention_media_days,
        dpo_name=privacy.dpo_name,
        dpo_email=privacy.dpo_email,
        privacy_policy_version=privacy.privacy_policy_version,
        privacy_policy_url=privacy.privacy_policy_url,
        camera_notice_text=privacy.camera_notice_text,
    )


@router.get("/privacy/{slug}", response_model=PublicPrivacyOut)
def public_privacy(slug: str, db: Session = Depends(get_db)) -> PublicPrivacyOut:
    organization = organization_by_slug(db, slug)
    if organization is None:
        raise HTTPException(status_code=404, detail="organização não encontrada")
    return _public_payload(organization, _privacy(db, organization.id))


@router.post("/privacy/{slug}/requests", response_model=DsrOut, status_code=201)
def create_data_subject_request(
    slug: str,
    payload: DsrCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> DsrOut:
    organization = organization_by_slug(db, slug)
    if organization is None:
        raise HTTPException(status_code=404, detail="organização não encontrada")
    ip = client_ip(request) or "unknown"
    key = f"dsr:{ip}"
    if login_limiter.blocked(key, attempts=5, window_s=3600):
        raise HTTPException(status_code=429, detail="muitas solicitações; tente mais tarde")
    login_limiter.hit(key, window_s=3600)
    if payload.date_range_start and payload.date_range_end:
        if payload.date_range_start > payload.date_range_end:
            raise HTTPException(status_code=422, detail="intervalo de datas inválido")
    if payload.camera_profile_id:
        profile = (
            db.query(CameraProfile)
            .filter(
                CameraProfile.id == payload.camera_profile_id,
                CameraProfile.organization_id == organization.id,
            )
            .one_or_none()
        )
        if profile is None:
            raise HTTPException(status_code=404, detail="perfil não encontrado")

    protocol = generate_protocol()
    while db.query(DataSubjectRequest).filter(DataSubjectRequest.protocol == protocol).first():
        protocol = generate_protocol()
    dsr = DataSubjectRequest(
        organization_id=organization.id,
        protocol=protocol,
        type=payload.type,
        status="new",
        requester_name=payload.requester_name,
        requester_email=str(payload.requester_email),
        description=payload.description,
        date_range_start=payload.date_range_start,
        date_range_end=payload.date_range_end,
        camera_profile_id=payload.camera_profile_id,
        due_at=utcnow() + timedelta(days=15),
    )
    db.add(dsr)
    db.commit()
    db.refresh(dsr)
    log_audit(
        db,
        organization_id=organization.id,
        action="dsr.create",
        resource_type="data_subject_request",
        resource_id=dsr.id,
        metadata={"protocol": protocol, "type": payload.type},
        request=request,
        commit=True,
    )
    return DsrOut.model_validate(dsr)


@router.get("/orgs/{slug}/privacy", response_model=PrivacySettingsOut)
def get_privacy_settings(
    principal: AuthPrincipal = Depends(require_org(PRIVACY_MANAGE)),
    db: Session = Depends(get_db),
) -> PrivacySettingsOut:
    return PrivacySettingsOut.model_validate(
        _privacy(db, principal.organization_id or "")
    )


@router.put("/orgs/{slug}/privacy", response_model=PrivacySettingsOut)
def update_privacy_settings(
    payload: PrivacySettingsIn,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(PRIVACY_MANAGE)),
    db: Session = Depends(get_db),
) -> PrivacySettingsOut:
    privacy = _privacy(db, principal.organization_id or "")
    data = payload.model_dump()
    for field, value in data.items():
        setattr(privacy, field, value)
    db.commit()
    db.refresh(privacy)
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="privacy.update",
        resource_type="privacy_settings",
        resource_id=privacy.organization_id,
        metadata={key: value for key, value in data.items() if key != "camera_notice_text"},
        request=request,
        commit=True,
    )
    return PrivacySettingsOut.model_validate(privacy)


@router.get("/orgs/{slug}/data-subject-requests", response_model=list[DsrOut])
def list_dsr(
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthPrincipal = Depends(require_org(DSR_MANAGE)),
    db: Session = Depends(get_db),
) -> list[DsrOut]:
    query = db.query(DataSubjectRequest).filter(
        DataSubjectRequest.organization_id == principal.organization_id
    )
    if status:
        query = query.filter(DataSubjectRequest.status == status)
    rows = query.order_by(DataSubjectRequest.created_at.desc()).limit(limit).all()
    return [DsrOut.model_validate(row) for row in rows]


@router.patch("/orgs/{slug}/data-subject-requests/{dsr_id}", response_model=DsrOut)
def update_dsr(
    dsr_id: str,
    payload: DsrUpdate,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(DSR_MANAGE)),
    db: Session = Depends(get_db),
) -> DsrOut:
    dsr = scoped_get(
        db,
        DataSubjectRequest,
        principal.organization_id or "",
        dsr_id,
        detail="solicitação não encontrada",
    )
    if payload.assigned_user_id:
        membership = (
            db.query(Membership)
            .filter(
                Membership.user_id == payload.assigned_user_id,
                Membership.organization_id == principal.organization_id,
                Membership.status == "active",
            )
            .one_or_none()
        )
        if membership is None:
            raise HTTPException(status_code=422, detail="responsável não é membro ativo")
    dsr.status = payload.status
    if payload.assigned_user_id is not None:
        dsr.assigned_user_id = payload.assigned_user_id
    if payload.resolution is not None:
        dsr.resolution = payload.resolution
    db.commit()
    db.refresh(dsr)
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="dsr.update",
        resource_type="data_subject_request",
        resource_id=dsr.id,
        metadata={"status": dsr.status},
        request=request,
        commit=True,
    )
    return DsrOut.model_validate(dsr)


def _matching_events(db: Session, dsr: DataSubjectRequest) -> list[Event]:
    query = db.query(Event).filter(Event.organization_id == dsr.organization_id)
    if dsr.date_range_start:
        query = query.filter(Event.created_at >= dsr.date_range_start)
    if dsr.date_range_end:
        query = query.filter(Event.created_at <= dsr.date_range_end)
    if dsr.camera_profile_id:
        query = query.join(Video, Video.id == Event.video_id).filter(
            Video.profile_id == dsr.camera_profile_id
        )
    return query.order_by(Event.created_at.asc()).all()


@router.get("/orgs/{slug}/data-subject-requests/{dsr_id}/export")
def export_dsr(
    dsr_id: str,
    principal: AuthPrincipal = Depends(require_org(DSR_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    dsr = scoped_get(
        db,
        DataSubjectRequest,
        principal.organization_id or "",
        dsr_id,
        detail="solicitação não encontrada",
    )
    events = _matching_events(db, dsr)
    videos = {
        video.id: {
            "id": video.id,
            "filename": video.filename,
            "recorded_at": video.recorded_at,
            "created_at": video.created_at.isoformat() if video.created_at else None,
        }
        for video in db.query(Video)
        .filter(
            Video.organization_id == dsr.organization_id,
            Video.id.in_({event.video_id for event in events}),
        )
        .all()
    } if events else {}
    return {
        "protocol": dsr.protocol,
        "type": dsr.type,
        "organization_id": dsr.organization_id,
        "date_range": {
            "start": dsr.date_range_start.isoformat() if dsr.date_range_start else None,
            "end": dsr.date_range_end.isoformat() if dsr.date_range_end else None,
        },
        "videos": list(videos.values()),
        "events": [
            {
                "id": event.id,
                "video_id": event.video_id,
                "start_s": event.start_s,
                "end_s": event.end_s,
                "start_wallclock": event.start_wallclock,
                "end_wallclock": event.end_wallclock,
                "review_status": event.review_status,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
    }


@router.post("/orgs/{slug}/data-subject-requests/{dsr_id}/execute-deletion")
def execute_dsr_deletion(
    dsr_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(DSR_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    dsr = scoped_get(
        db,
        DataSubjectRequest,
        principal.organization_id or "",
        dsr_id,
        detail="solicitação não encontrada",
    )
    now = utcnow()
    holds = {
        hold.resource_id
        for hold in db.query(LegalHold)
        .filter(
            LegalHold.organization_id == dsr.organization_id,
            LegalHold.resource_type == "event",
        )
        .all()
        if ensure_utc(hold.expires_at) is None or ensure_utc(hold.expires_at) > now
    }
    storage = get_storage(get_settings()) if get_settings().storage_backend == "s3" else None
    deleted = 0
    skipped = 0
    for event in _matching_events(db, dsr):
        if event.id in holds:
            skipped += 1
            continue
        for raw in (event.clip_path, event.thumbnail_path):
            if raw:
                Path(raw).unlink(missing_ok=True)
        for key in (event.clip_storage_key, event.thumbnail_storage_key):
            if key and storage is not None:
                storage.delete(key)
        event.clip_path = None
        event.thumbnail_path = None
        event.clip_storage_key = None
        event.thumbnail_storage_key = None
        deleted += 1
    dsr.resolution = f"mídia de {deleted} evento(s) excluída; {skipped} sob legal hold"
    if dsr.status != "completed":
        dsr.status = "in_progress"
    db.commit()
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="dsr.execute_deletion",
        resource_type="data_subject_request",
        resource_id=dsr.id,
        metadata={"deleted": deleted, "skipped": skipped},
        request=request,
        commit=True,
    )
    return {"deleted_events": deleted, "skipped_legal_hold": skipped}


@router.get("/orgs/{slug}/legal-holds", response_model=list[LegalHoldOut])
def list_legal_holds(
    principal: AuthPrincipal = Depends(require_org(PRIVACY_MANAGE)),
    db: Session = Depends(get_db),
) -> list[LegalHoldOut]:
    rows = (
        db.query(LegalHold)
        .filter(LegalHold.organization_id == principal.organization_id)
        .order_by(LegalHold.created_at.desc())
        .all()
    )
    return [LegalHoldOut.model_validate(row) for row in rows]


@router.post("/orgs/{slug}/legal-holds", response_model=LegalHoldOut, status_code=201)
def create_legal_hold(
    payload: LegalHoldIn,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(PRIVACY_MANAGE)),
    db: Session = Depends(get_db),
) -> LegalHoldOut:
    if payload.resource_type == "video":
        resource = (
            db.query(Video)
            .filter(
                Video.id == payload.resource_id,
                Video.organization_id == principal.organization_id,
            )
            .one_or_none()
        )
    else:
        resource = (
            db.query(Event)
            .filter(
                Event.id == payload.resource_id,
                Event.organization_id == principal.organization_id,
            )
            .one_or_none()
        )
    if resource is None:
        raise HTTPException(status_code=404, detail="recurso não encontrado")
    hold = LegalHold(
        organization_id=principal.organization_id or "",
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        reason=payload.reason,
        created_by_user_id=principal.user_id,
        expires_at=payload.expires_at,
    )
    db.add(hold)
    db.commit()
    db.refresh(hold)
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="legal_hold.create",
        resource_type="legal_hold",
        resource_id=hold.id,
        metadata={"target": payload.resource_id, "kind": payload.resource_type},
        request=request,
        commit=True,
    )
    return LegalHoldOut.model_validate(hold)


@router.delete("/orgs/{slug}/legal-holds/{hold_id}", status_code=204)
def delete_legal_hold(
    hold_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(PRIVACY_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    hold = scoped_get(
        db, LegalHold, principal.organization_id or "", hold_id, detail="legal hold não encontrado"
    )
    db.delete(hold)
    db.commit()
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="legal_hold.delete",
        resource_type="legal_hold",
        resource_id=hold_id,
        request=request,
        commit=True,
    )


@router.post("/orgs/{slug}/retention/run")
def run_org_retention(
    request: Request,
    principal: AuthPrincipal = Depends(require_org(PRIVACY_MANAGE)),
    db: Session = Depends(get_db),
) -> dict:
    counts = run_retention(db, organization_id=principal.organization_id)
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="retention.run",
        metadata=counts,
        request=request,
        commit=True,
    )
    return counts
