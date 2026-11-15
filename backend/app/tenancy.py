from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeVar

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from .models import (
    AccessLog,
    ApiKey,
    AuditLog,
    Membership,
    Organization,
    Session as AuthSession,
    User,
)
from .security import ensure_utc, utcnow

ModelT = TypeVar("ModelT")


@dataclass
class AuthPrincipal:
    """Authenticated identity resolved for a request.

    ``organization`` is set for tenant-scoped routes and for API keys (whose
    organization is implicit in the credential).
    """

    user: User | None = None
    session: AuthSession | None = None
    api_key: ApiKey | None = None
    organization: Organization | None = None
    membership: Membership | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)
    scopes: frozenset[str] = field(default_factory=frozenset)

    @property
    def user_id(self) -> str | None:
        return self.user.id if self.user else None

    @property
    def organization_id(self) -> str | None:
        return self.organization.id if self.organization else None

    @property
    def is_api_key(self) -> bool:
        return self.api_key is not None

    def require_permission(self, permission: str) -> None:
        if permission not in self.permissions:
            raise HTTPException(status_code=403, detail="permissão insuficiente")

    def require_scope(self, scope: str) -> None:
        if scope not in self.scopes:
            raise HTTPException(status_code=403, detail="escopo insuficiente")


def organization_by_slug(
    db: Session, slug: str, *, include_suspended: bool = False
) -> Organization | None:
    organization = db.query(Organization).filter(Organization.slug == slug).one_or_none()
    if organization is None:
        return None
    if not include_suspended and organization.status != "active":
        return None
    return organization


def active_membership(
    db: Session, user_id: str, organization_id: str
) -> Membership | None:
    return (
        db.query(Membership)
        .filter(
            Membership.user_id == user_id,
            Membership.organization_id == organization_id,
            Membership.status == "active",
        )
        .one_or_none()
    )


def effective_permissions(membership: Membership | None) -> frozenset[str]:
    if membership is None:
        return frozenset()
    values: set[str] = set()
    for group in membership.permission_groups:
        values.update(group.permissions or [])
    return frozenset(values)


def build_tenant_context(
    db: Session, *, user: User | None, session: AuthSession | None, organization: Organization
) -> AuthPrincipal:
    if user is None:
        raise HTTPException(status_code=401, detail="autenticação necessária")
    membership = active_membership(db, user.id, organization.id)
    return AuthPrincipal(
        user=user,
        session=session,
        organization=organization,
        membership=membership,
        permissions=effective_permissions(membership),
    )


def build_api_key_context(api_key: ApiKey, organization: Organization) -> AuthPrincipal:
    return AuthPrincipal(
        api_key=api_key,
        organization=organization,
        permissions=frozenset(),
        scopes=frozenset(api_key.scopes or []),
    )


# ---------------------------------------------------------------------------
# Scoped queries. Every tenant-owned read goes through these helpers.
# ---------------------------------------------------------------------------


def scoped_query(db: Session, model: type[ModelT], organization_id: str):
    return db.query(model).filter(model.organization_id == organization_id)


def scoped_get(
    db: Session,
    model: type[ModelT],
    organization_id: str,
    resource_id: str,
    *,
    detail: str = "recurso não encontrado",
) -> ModelT:
    resource = (
        db.query(model)
        .filter(
            model.organization_id == organization_id,
            model.id == resource_id,
        )
        .one_or_none()
    )
    if resource is None:
        # 404 instead of 403 so cross-tenant probes cannot confirm existence.
        raise HTTPException(status_code=404, detail=detail)
    return resource


def session_is_valid(session: AuthSession) -> bool:
    now = utcnow()
    if session.revoked_at is not None:
        return False
    expires = ensure_utc(session.expires_at)
    return expires is not None and expires > now


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    cloudflare = request.headers.get("cf-connecting-ip")
    if cloudflare:
        return cloudflare.strip()[:64]
    if request.client is not None:
        return request.client.host[:64]
    return None


def request_user_agent(request: Request | None) -> str | None:
    if request is None:
        return None
    value = request.headers.get("user-agent")
    return value[:500] if value else None


def log_audit(
    db: Session,
    *,
    organization_id: str | None,
    actor_user_id: str | None = None,
    actor_api_key_id: str | None = None,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    request: Request | None = None,
    commit: bool = False,
) -> AuditLog:
    entry = AuditLog(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_api_key_id=actor_api_key_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata_json=metadata or {},
        ip=client_ip(request),
        user_agent=request_user_agent(request),
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry


def log_access(
    db: Session,
    *,
    organization_id: str,
    principal: AuthPrincipal,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    request: Request | None = None,
    commit: bool = False,
) -> AccessLog:
    entry = AccessLog(
        organization_id=organization_id,
        user_id=principal.user_id,
        api_key_id=principal.api_key.id if principal.api_key else None,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip=client_ip(request),
        user_agent=request_user_agent(request),
    )
    db.add(entry)
    if commit:
        db.commit()
    return entry
