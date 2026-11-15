from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import ApiKey, Organization, Session as AuthSession, User
from .security import (
    api_key_secret_hash,
    constant_time_equal,
    ensure_utc,
    hash_token,
    new_csrf_token,
    split_api_key,
    utcnow,
)
from .tenancy import (
    AuthPrincipal,
    active_membership,
    build_api_key_context,
    build_tenant_context,
    effective_permissions,
    organization_by_slug,
    session_is_valid,
)


def _settings():
    return get_settings()


def session_from_request(
    request: Request, db: Session
) -> tuple[User | None, AuthSession | None]:
    settings = _settings()
    raw = request.cookies.get(settings.session_cookie)
    if not raw:
        return None, None
    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == hash_token(raw))
        .one_or_none()
    )
    if session is None or not session_is_valid(session):
        return None, None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None, None
    return user, session


def api_key_from_request(request: Request, db: Session) -> tuple[ApiKey, Organization] | None:
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization[7:].strip()
    parsed = split_api_key(token)
    if parsed is None:
        return None
    prefix, secret = parsed
    api_key = db.query(ApiKey).filter(ApiKey.prefix == prefix).one_or_none()
    if api_key is None or api_key.revoked_at is not None:
        return None
    if not constant_time_equal(api_key.secret_hash, api_key_secret_hash(secret)):
        return None
    expires = ensure_utc(api_key.expires_at)
    if expires is not None and expires <= utcnow():
        return None
    organization = db.get(Organization, api_key.organization_id)
    if organization is None or organization.status != "active":
        return None
    api_key.last_used_at = utcnow()
    db.commit()
    return api_key, organization


def current_user_principal(
    request: Request, db: Session = Depends(get_db)
) -> AuthPrincipal:
    user, session = session_from_request(request, db)
    if user is None or session is None:
        raise HTTPException(status_code=401, detail="autenticação necessária")
    session.last_seen_at = utcnow()
    db.commit()
    organization = None
    membership = None
    permissions: frozenset[str] = frozenset()
    if session.active_organization_id:
        organization = db.get(Organization, session.active_organization_id)
        if organization is not None and organization.status == "active":
            membership = active_membership(db, user.id, organization.id)
            permissions = effective_permissions(membership)
        else:
            organization = None
    return AuthPrincipal(
        user=user,
        session=session,
        organization=organization,
        membership=membership,
        permissions=permissions,
    )


def _resolve_for_org(request: Request, db: Session, slug: str) -> AuthPrincipal:
    organization = organization_by_slug(db, slug)
    if organization is None:
        raise HTTPException(status_code=404, detail="organização não encontrada")

    api_key, key_org = (None, None)
    parsed_key = api_key_from_request(request, db)
    if parsed_key is not None:
        api_key, key_org = parsed_key
        if key_org.id != organization.id:
            # Cross-tenant machine access must look like a missing resource.
            raise HTTPException(status_code=404, detail="organização não encontrada")
        return build_api_key_context(api_key, organization)

    user, session = session_from_request(request, db)
    if user is None or session is None:
        raise HTTPException(status_code=401, detail="autenticação necessária")
    membership = active_membership(db, user.id, organization.id)
    if membership is None:
        # Do not disclose whether the organization exists to non-members.
        raise HTTPException(status_code=404, detail="organização não encontrada")
    session.active_organization_id = organization.id
    session.last_seen_at = utcnow()
    db.commit()
    return AuthPrincipal(
        user=user,
        session=session,
        organization=organization,
        membership=membership,
        permissions=effective_permissions(membership),
    )


def require_org(permission: str | None = None) -> Callable[..., AuthPrincipal]:
    """Dependency factory for routes scoped by ``{slug}``.

    Session authentication is required for organization administration and
    catalog routes. API keys are accepted only on dedicated machine routes.
    """

    def dependency(
        slug: str, request: Request, db: Session = Depends(get_db)
    ) -> AuthPrincipal:
        principal = _resolve_for_org(request, db, slug)
        if principal.is_api_key:
            raise HTTPException(status_code=403, detail="API key não autorizada aqui")
        if permission is not None:
            principal.require_permission(permission)
        return principal

    return dependency


def require_api_key(scope: str) -> Callable[..., AuthPrincipal]:
    def dependency(request: Request, db: Session = Depends(get_db)) -> AuthPrincipal:
        parsed = api_key_from_request(request, db)
        if parsed is None:
            raise HTTPException(status_code=401, detail="API key inválida")
        api_key, organization = parsed
        principal = build_api_key_context(api_key, organization)
        principal.require_scope(scope)
        return principal

    return dependency


# ---------------------------------------------------------------------------
# Cookies and CSRF
# ---------------------------------------------------------------------------


def set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    settings = _settings()
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookies(response: Response) -> None:
    settings = _settings()
    response.delete_cookie(settings.session_cookie, path="/")
    response.delete_cookie(settings.csrf_cookie, path="/")


def issue_csrf_token(response: Response) -> str:
    token = new_csrf_token()
    settings = _settings()
    response.set_cookie(
        settings.csrf_cookie,
        token,
        max_age=settings.session_ttl_hours * 3600,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return token


def csrf_is_valid(request: Request) -> bool:
    settings = _settings()
    cookie = request.cookies.get(settings.csrf_cookie)
    header = request.headers.get("x-csrf-token")
    if not cookie or not header:
        return False
    return constant_time_equal(cookie, header)


def require_csrf(request: Request) -> None:
    if not _settings().csrf_enabled:
        return
    if not csrf_is_valid(request):
        raise HTTPException(status_code=403, detail="CSRF token inválido")
