from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import require_org
from ..db import get_db
from ..models import CameraProfile, Video
from ..permissions import PROFILES_MANAGE, PROFILES_VIEW
from ..schemas import ProfileIn, ProfileOut
from ..tenancy import AuthPrincipal, scoped_get, scoped_query

router = APIRouter(prefix="/orgs/{slug}/profiles", tags=["profiles"])


def _validate_masks(masks: list[dict[str, Any]]) -> None:
    for mask in masks:
        try:
            if {"x", "y", "w", "h"} <= set(mask):
                x, y, w, h = (float(mask[k]) for k in ("x", "y", "w", "h"))
            elif {"x1", "y1", "x2", "y2"} <= set(mask):
                x1, y1, x2, y2 = (float(mask[k]) for k in ("x1", "y1", "x2", "y2"))
                x, y, w, h = x1, y1, x2 - x1, y2 - y1
            else:
                raise ValueError("máscara precisa de x/y/w/h ou x1/y1/x2/y2")
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=f"máscara inválida: {exc}") from exc
        if min(x, y, w, h) < 0 or x + w > 1.0001 or y + h > 1.0001:
            raise HTTPException(
                status_code=422,
                detail="coordenadas da máscara precisam estar normalizadas entre 0 e 1",
            )
        if w <= 0 or h <= 0:
            raise HTTPException(status_code=422, detail="máscara com largura/altura zero")


@router.get("", response_model=list[ProfileOut])
def list_profiles(
    principal: AuthPrincipal = Depends(require_org(PROFILES_VIEW)),
    db: Session = Depends(get_db),
) -> list[ProfileOut]:
    profiles = (
        scoped_query(db, CameraProfile, principal.organization_id or "")
        .order_by(CameraProfile.created_at.asc())
        .all()
    )
    return [ProfileOut.model_validate(profile) for profile in profiles]


@router.post("", response_model=ProfileOut, status_code=201)
def create_profile(
    payload: ProfileIn,
    principal: AuthPrincipal = Depends(require_org(PROFILES_MANAGE)),
    db: Session = Depends(get_db),
) -> ProfileOut:
    _validate_masks(payload.masks)
    organization_id = principal.organization_id or ""
    existing = (
        db.query(CameraProfile)
        .filter(
            CameraProfile.organization_id == organization_id,
            CameraProfile.name == payload.name,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="já existe um perfil com esse nome")
    profile = CameraProfile(
        organization_id=organization_id,
        name=payload.name,
        masks=payload.masks,
        roi=payload.roi,
        settings=payload.settings,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.get("/{profile_id}", response_model=ProfileOut)
def get_profile(
    profile_id: str,
    principal: AuthPrincipal = Depends(require_org(PROFILES_VIEW)),
    db: Session = Depends(get_db),
) -> ProfileOut:
    profile = scoped_get(
        db, CameraProfile, principal.organization_id or "", profile_id, detail="perfil não encontrado"
    )
    return ProfileOut.model_validate(profile)


@router.put("/{profile_id}", response_model=ProfileOut)
def update_profile(
    profile_id: str,
    payload: ProfileIn,
    principal: AuthPrincipal = Depends(require_org(PROFILES_MANAGE)),
    db: Session = Depends(get_db),
) -> ProfileOut:
    _validate_masks(payload.masks)
    profile = scoped_get(
        db, CameraProfile, principal.organization_id or "", profile_id, detail="perfil não encontrado"
    )
    duplicate = (
        db.query(CameraProfile)
        .filter(
            CameraProfile.organization_id == profile.organization_id,
            CameraProfile.name == payload.name,
            CameraProfile.id != profile.id,
        )
        .first()
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="já existe um perfil com esse nome")
    profile.name = payload.name
    profile.masks = payload.masks
    profile.roi = payload.roi
    profile.settings = payload.settings
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile)


@router.delete("/{profile_id}", status_code=204)
def delete_profile(
    profile_id: str,
    principal: AuthPrincipal = Depends(require_org(PROFILES_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    profile = scoped_get(
        db, CameraProfile, principal.organization_id or "", profile_id, detail="perfil não encontrado"
    )
    in_use = (
        db.query(Video)
        .filter(
            Video.organization_id == profile.organization_id,
            Video.profile_id == profile.id,
        )
        .first()
    )
    if in_use is not None:
        raise HTTPException(status_code=409, detail="perfil em uso por vídeos")
    db.delete(profile)
    db.commit()
