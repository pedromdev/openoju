from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..auth import current_user_principal, require_org
from ..db import get_db
from ..models import (
    ApiKey,
    AuditLog,
    Membership,
    Organization,
    PermissionGroup,
    User,
)
from ..permissions import (
    API_KEY_SCOPES,
    AUDIT_VIEW,
    API_KEYS_MANAGE,
    GROUPS_MANAGE,
    MEMBERS_INVITE,
    MEMBERS_MANAGE,
    MEMBERS_VIEW,
    ORGANIZATION_VIEW,
    PERMISSIONS,
)
from ..schemas import (
    ApiKeyCreate,
    ApiKeyCreatedOut,
    ApiKeyOut,
    AuditLogOut,
    GroupIn,
    GroupOut,
    InviteOut,
    InviteRequest,
    MemberOut,
    MemberUpdate,
    OrganizationOut,
)
from ..security import generate_api_key, utcnow
from ..services.organizations import invite_or_activate_member
from ..tenancy import AuthPrincipal, log_audit

router = APIRouter(tags=["organizations"])


@router.get("/organizations", response_model=list[OrganizationOut])
def list_my_organizations(
    principal: AuthPrincipal = Depends(current_user_principal),
    db: Session = Depends(get_db),
) -> list[OrganizationOut]:
    rows = (
        db.query(Organization)
        .join(Membership, Membership.organization_id == Organization.id)
        .filter(
            Membership.user_id == principal.user_id,
            Membership.status == "active",
            Organization.status == "active",
        )
        .order_by(Organization.name.asc())
        .all()
    )
    return [OrganizationOut.model_validate(row) for row in rows]


@router.get("/orgs/{slug}", response_model=OrganizationOut)
def get_organization(
    principal: AuthPrincipal = Depends(require_org(ORGANIZATION_VIEW)),
) -> OrganizationOut:
    assert principal.organization is not None
    return OrganizationOut.model_validate(principal.organization)


def _member_out(membership: Membership) -> MemberOut:
    return MemberOut(
        id=membership.id,
        user_id=membership.user_id,
        email=membership.user.email,
        display_name=membership.user.display_name,
        status=membership.status,
        groups=[
            GroupOut(
                id=group.id,
                name=group.name,
                description=group.description,
                permissions=list(group.permissions or []),
                is_system=group.is_system,
            )
            for group in membership.permission_groups
        ],
        created_at=membership.created_at,
    )


def _org_group(
    db: Session, organization_id: str, group_id: str
) -> PermissionGroup:
    group = (
        db.query(PermissionGroup)
        .filter(
            PermissionGroup.id == group_id,
            PermissionGroup.organization_id == organization_id,
        )
        .one_or_none()
    )
    if group is None:
        raise HTTPException(status_code=404, detail="grupo não encontrado")
    return group


def _validate_permissions(permissions: list[str]) -> list[str]:
    unknown = sorted(set(permissions) - set(PERMISSIONS))
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"permissões desconhecidas: {unknown}"
        )
    return sorted(set(permissions))


@router.get("/orgs/{slug}/members", response_model=list[MemberOut])
def list_members(
    principal: AuthPrincipal = Depends(require_org(MEMBERS_VIEW)),
    db: Session = Depends(get_db),
) -> list[MemberOut]:
    memberships = (
        db.query(Membership)
        .join(User, User.id == Membership.user_id)
        .filter(Membership.organization_id == principal.organization_id)
        .order_by(User.email.asc())
        .all()
    )
    return [_member_out(membership) for membership in memberships]


@router.post("/orgs/{slug}/members/invite", response_model=InviteOut, status_code=201)
def invite_member(
    payload: InviteRequest,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(MEMBERS_INVITE)),
    db: Session = Depends(get_db),
) -> InviteOut:
    assert principal.organization is not None and principal.user is not None
    group_ids = payload.group_ids
    if not group_ids:
        viewer = (
            db.query(PermissionGroup)
            .filter(
                PermissionGroup.organization_id == principal.organization_id,
                PermissionGroup.name == "Viewer",
            )
            .one_or_none()
        )
        group_ids = [viewer.id] if viewer else []
    for group_id in group_ids:
        _org_group(db, principal.organization_id or "", group_id)
    try:
        membership, token = invite_or_activate_member(
            db,
            organization=principal.organization,
            email=str(payload.email),
            group_ids=group_ids,
            invited_by=principal.user,
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    from ..models import Invitation

    invitation = (
        db.query(Invitation)
        .filter(Invitation.organization_id == principal.organization_id)
        .order_by(Invitation.created_at.desc())
        .first()
    )
    assert invitation is not None
    return InviteOut(
        membership_id=membership.id,
        invitation_id=invitation.id,
        token=token,
        expires_at=invitation.expires_at,
    )


def _has_owner_group(membership: Membership) -> bool:
    return any(group.name == "Owner" for group in membership.permission_groups)


def _ensure_not_last_owner(
    db: Session,
    membership: Membership,
    *,
    next_status: str,
    next_groups: list[PermissionGroup] | None,
) -> None:
    if not _has_owner_group(membership):
        return
    owners = (
        db.query(Membership)
        .join(Membership.permission_groups)
        .filter(
            Membership.organization_id == membership.organization_id,
            Membership.status == "active",
            PermissionGroup.name == "Owner",
        )
        .all()
    )
    owner_ids = {owner.id for owner in owners}
    groups = next_groups if next_groups is not None else list(membership.permission_groups)
    keeps_owner = next_status == "active" and any(
        group.name == "Owner" for group in groups
    )
    if membership.id in owner_ids and len(owner_ids) <= 1 and not keeps_owner:
        raise HTTPException(
            status_code=409, detail="a organização precisa de pelo menos um owner ativo"
        )


@router.patch("/orgs/{slug}/members/{membership_id}", response_model=MemberOut)
def update_member(
    membership_id: str,
    payload: MemberUpdate,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(MEMBERS_MANAGE)),
    db: Session = Depends(get_db),
) -> MemberOut:
    membership = (
        db.query(Membership)
        .filter(
            Membership.id == membership_id,
            Membership.organization_id == principal.organization_id,
        )
        .one_or_none()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="membro não encontrado")

    groups: list[PermissionGroup] = []
    if payload.group_ids is not None:
        groups = [
            _org_group(db, principal.organization_id or "", group_id)
            for group_id in payload.group_ids
        ]
    else:
        groups = list(membership.permission_groups)

    _ensure_not_last_owner(
        db,
        membership,
        next_status=payload.status,
        next_groups=groups if payload.group_ids is not None else None,
    )
    membership.status = payload.status
    membership.permission_groups = groups
    db.commit()
    db.refresh(membership)
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="member.update",
        resource_type="membership",
        resource_id=membership.id,
        metadata={
            "status": payload.status,
            "groups": [group.name for group in groups],
        },
        request=request,
        commit=True,
    )
    return _member_out(membership)


@router.get("/orgs/{slug}/groups", response_model=list[GroupOut])
def list_groups(
    principal: AuthPrincipal = Depends(require_org(GROUPS_MANAGE)),
    db: Session = Depends(get_db),
) -> list[GroupOut]:
    groups = (
        db.query(PermissionGroup)
        .filter(PermissionGroup.organization_id == principal.organization_id)
        .order_by(PermissionGroup.is_system.desc(), PermissionGroup.name.asc())
        .all()
    )
    return [
        GroupOut(
            id=group.id,
            name=group.name,
            description=group.description,
            permissions=list(group.permissions or []),
            is_system=group.is_system,
        )
        for group in groups
    ]


@router.post("/orgs/{slug}/groups", response_model=GroupOut, status_code=201)
def create_group(
    payload: GroupIn,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(GROUPS_MANAGE)),
    db: Session = Depends(get_db),
) -> GroupOut:
    permissions = _validate_permissions(payload.permissions)
    duplicate = (
        db.query(PermissionGroup)
        .filter(
            PermissionGroup.organization_id == principal.organization_id,
            PermissionGroup.name == payload.name,
        )
        .one_or_none()
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="já existe um grupo com esse nome")
    group = PermissionGroup(
        organization_id=principal.organization_id or "",
        name=payload.name,
        description=payload.description,
        permissions=permissions,
        is_system=False,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="group.create",
        resource_type="permission_group",
        resource_id=group.id,
        metadata={"name": group.name, "permissions": permissions},
        request=request,
        commit=True,
    )
    return GroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        permissions=list(group.permissions or []),
        is_system=group.is_system,
    )


@router.put("/orgs/{slug}/groups/{group_id}", response_model=GroupOut)
def update_group(
    group_id: str,
    payload: GroupIn,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(GROUPS_MANAGE)),
    db: Session = Depends(get_db),
) -> GroupOut:
    group = _org_group(db, principal.organization_id or "", group_id)
    if group.name == "Owner":
        raise HTTPException(status_code=409, detail="o grupo Owner é imutável")
    if group.is_system and payload.name != group.name:
        raise HTTPException(
            status_code=409, detail="não é possível renomear um grupo de sistema"
        )
    permissions = _validate_permissions(payload.permissions)
    duplicate = (
        db.query(PermissionGroup)
        .filter(
            PermissionGroup.organization_id == principal.organization_id,
            PermissionGroup.name == payload.name,
            PermissionGroup.id != group.id,
        )
        .one_or_none()
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="já existe um grupo com esse nome")
    group.name = payload.name
    group.description = payload.description
    group.permissions = permissions
    db.commit()
    db.refresh(group)
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="group.update",
        resource_type="permission_group",
        resource_id=group.id,
        metadata={"name": group.name, "permissions": permissions},
        request=request,
        commit=True,
    )
    return GroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        permissions=list(group.permissions or []),
        is_system=group.is_system,
    )


@router.get("/orgs/{slug}/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(
    principal: AuthPrincipal = Depends(require_org(API_KEYS_MANAGE)),
    db: Session = Depends(get_db),
) -> list[ApiKeyOut]:
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.organization_id == principal.organization_id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return [ApiKeyOut.model_validate(key) for key in keys]


@router.post("/orgs/{slug}/api-keys", response_model=ApiKeyCreatedOut, status_code=201)
def create_api_key(
    payload: ApiKeyCreate,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(API_KEYS_MANAGE)),
    db: Session = Depends(get_db),
) -> ApiKeyCreatedOut:
    scopes = sorted(set(payload.scopes or ["ingest:write"]))
    unknown = sorted(set(scopes) - set(API_KEY_SCOPES))
    if unknown:
        raise HTTPException(status_code=422, detail=f"escopos desconhecidos: {unknown}")
    full_key, prefix, secret_hash = generate_api_key()
    api_key = ApiKey(
        organization_id=principal.organization_id or "",
        name=payload.name,
        prefix=prefix,
        secret_hash=secret_hash,
        scopes=scopes,
        created_by_user_id=principal.user_id,
        expires_at=payload.expires_at,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="api_key.create",
        resource_type="api_key",
        resource_id=api_key.id,
        metadata={"name": api_key.name, "scopes": scopes, "prefix": prefix},
        request=request,
        commit=True,
    )
    return ApiKeyCreatedOut(api_key=ApiKeyOut.model_validate(api_key), key=full_key)


@router.delete("/orgs/{slug}/api-keys/{key_id}", status_code=204)
def revoke_api_key(
    key_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(API_KEYS_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    api_key = (
        db.query(ApiKey)
        .filter(
            ApiKey.id == key_id,
            ApiKey.organization_id == principal.organization_id,
        )
        .one_or_none()
    )
    if api_key is None:
        raise HTTPException(status_code=404, detail="API key não encontrada")
    api_key.revoked_at = utcnow()
    db.commit()
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="api_key.revoke",
        resource_type="api_key",
        resource_id=api_key.id,
        metadata={"prefix": api_key.prefix},
        request=request,
        commit=True,
    )


@router.get("/orgs/{slug}/audit", response_model=list[AuditLogOut])
def list_audit(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: AuthPrincipal = Depends(require_org(AUDIT_VIEW)),
    db: Session = Depends(get_db),
) -> list[AuditLogOut]:
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.organization_id == principal.organization_id)
        .order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [AuditLogOut.model_validate(log) for log in logs]
