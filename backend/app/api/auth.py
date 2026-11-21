from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import oidc
from ..auth import (
    clear_session_cookies,
    current_user_principal,
    issue_csrf_token,
    set_session_cookies,
)
from ..config import get_settings
from ..db import get_db
from ..models import (
    IdentityProvider,
    Invitation,
    Membership,
    Organization,
    PermissionGroup,
    Session as AuthSession,
    User,
    utcnow,
)
from ..schemas import (
    CsrfOut,
    GroupOut,
    InvitationAcceptRequest,
    InvitationInfoOut,
    LoginRequest,
    MeOut,
    OrganizationOut,
    SetupRequest,
    SetupStatusOut,
    SwitchOrganizationRequest,
    UserOut,
)
from ..security import (
    constant_time_equal,
    hash_password,
    hash_token,
    limiter_for,
    new_session_token,
    normalize_email,
    session_expiry,
    verify_password,
)
from ..services.organizations import create_organization_with_owner, setup_required
from ..tenancy import (
    AuthPrincipal,
    active_membership,
    client_ip,
    effective_permissions,
    log_audit,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _me(principal: AuthPrincipal) -> MeOut:
    if principal.user is None:
        raise HTTPException(status_code=401, detail="autenticação necessária")
    groups: list[GroupOut] = []
    if principal.membership is not None:
        groups = [
            GroupOut(
                id=group.id,
                name=group.name,
                description=group.description,
                permissions=list(group.permissions or []),
                is_system=group.is_system,
            )
            for group in principal.membership.permission_groups
        ]
    return MeOut(
        user=UserOut.model_validate(principal.user),
        organization=(
            OrganizationOut.model_validate(principal.organization)
            if principal.organization
            else None
        ),
        permissions=sorted(principal.permissions),
        groups=groups,
    )


def _create_session(
    db: Session,
    request: Request,
    user: User,
    *,
    auth_method: str = "local",
    identity_provider_id: str | None = None,
) -> tuple[AuthSession, str, str]:
    settings = get_settings()
    token = new_session_token()
    csrf = new_session_token()
    memberships = (
        db.query(Membership)
        .filter(Membership.user_id == user.id, Membership.status == "active")
        .all()
    )
    active_org = memberships[0].organization_id if len(memberships) == 1 else None
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        active_organization_id=active_org,
        auth_method=auth_method,
        identity_provider_id=identity_provider_id,
        user_agent=(request.headers.get("user-agent") or "")[:500] or None,
        ip=client_ip(request),
        expires_at=session_expiry(settings.session_ttl_hours),
        last_seen_at=utcnow(),
    )
    db.add(session)
    user.last_login_at = utcnow()
    db.commit()
    db.refresh(session)
    return session, token, csrf


@router.get("/setup/status", response_model=SetupStatusOut)
def setup_status(db: Session = Depends(get_db)) -> SetupStatusOut:
    settings = get_settings()
    return SetupStatusOut(
        setup_required=setup_required(db),
        oidc_enabled=settings.oidc_enabled,
    )


@router.post("/setup", response_model=MeOut, status_code=201)
def setup(
    payload: SetupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> MeOut:
    settings = get_settings()
    if not setup_required(db):
        raise HTTPException(status_code=409, detail="setup já foi concluído")
    if not settings.setup_token:
        raise HTTPException(
            status_code=503,
            detail="setup desabilitado: OJU_SETUP_TOKEN não configurado",
        )
    if not constant_time_equal(payload.token, settings.setup_token):
        raise HTTPException(status_code=403, detail="token de setup inválido")
    try:
        organization, user, membership = create_organization_with_owner(
            db,
            organization_name=payload.organization_name,
            slug=payload.organization_slug,
            owner_email=str(payload.owner_email),
            owner_password=payload.owner_password,
            owner_display_name=payload.owner_display_name,
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session, token, csrf = _create_session(db, request, user)
    set_session_cookies(response, token, csrf)
    principal = AuthPrincipal(
        user=user,
        session=session,
        organization=organization,
        membership=membership,
        permissions=effective_permissions(membership),
    )
    return _me(principal)


@router.post("/login", response_model=MeOut)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> MeOut:
    settings = get_settings()
    email = normalize_email(str(payload.email))
    ip = client_ip(request) or "unknown"
    limiter_key = f"{ip}:{email}"
    limiter = limiter_for(settings)
    if limiter.blocked(
        db,
        limiter_key,
        attempts=settings.login_rate_limit_attempts,
        window_s=settings.login_rate_limit_window_s,
    ):
        raise HTTPException(
            status_code=429, detail="muitas tentativas; tente novamente depois"
        )

    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        limiter.hit(db, limiter_key, window_s=settings.login_rate_limit_window_s)
        log_audit(
            db,
            organization_id=None,
            action="auth.login_failed",
            metadata={"email": email},
            request=request,
            commit=True,
        )
        raise HTTPException(status_code=401, detail="credenciais inválidas")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="usuário desativado")
    limiter.reset(db, limiter_key)
    session, token, csrf = _create_session(db, request, user)
    set_session_cookies(response, token, csrf)
    organization = None
    membership = None
    permissions: frozenset[str] = frozenset()
    if session.active_organization_id:
        from ..models import Organization

        organization = db.get(Organization, session.active_organization_id)
        if organization is not None:
            membership = active_membership(db, user.id, organization.id)
            permissions = effective_permissions(membership)
    principal = AuthPrincipal(
        user=user,
        session=session,
        organization=organization,
        membership=membership,
        permissions=permissions,
    )
    return _me(principal)


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    principal: AuthPrincipal = Depends(current_user_principal),
    db: Session = Depends(get_db),
) -> None:
    if principal.session is not None:
        principal.session.revoked_at = utcnow()
        db.commit()
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="auth.logout",
        request=request,
        commit=True,
    )
    clear_session_cookies(response)


@router.post("/logout-all", status_code=204)
def logout_all(
    request: Request,
    response: Response,
    principal: AuthPrincipal = Depends(current_user_principal),
    db: Session = Depends(get_db),
) -> None:
    db.query(AuthSession).filter(
        AuthSession.user_id == principal.user_id,
        AuthSession.revoked_at.is_(None),
    ).update({"revoked_at": utcnow()})
    db.commit()
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="auth.logout_all",
        request=request,
        commit=True,
    )
    clear_session_cookies(response)


@router.get("/me", response_model=MeOut)
def me(
    principal: AuthPrincipal = Depends(current_user_principal),
) -> MeOut:
    return _me(principal)


@router.post("/switch-organization", response_model=MeOut)
def switch_organization(
    payload: SwitchOrganizationRequest,
    request: Request,
    principal: AuthPrincipal = Depends(current_user_principal),
    db: Session = Depends(get_db),
) -> MeOut:
    if principal.session is None:
        raise HTTPException(status_code=401, detail="autenticação necessária")
    from ..tenancy import organization_by_slug

    organization = organization_by_slug(db, payload.slug)
    if organization is None:
        raise HTTPException(status_code=404, detail="organização não encontrada")
    membership = active_membership(db, principal.user_id or "", organization.id)
    if membership is None:
        raise HTTPException(status_code=404, detail="organização não encontrada")
    principal.session.active_organization_id = organization.id
    db.commit()
    refreshed = current_user_principal(request, db)
    log_audit(
        db,
        organization_id=organization.id,
        actor_user_id=principal.user_id,
        action="auth.switch_organization",
        resource_type="organization",
        resource_id=organization.id,
        request=request,
        commit=True,
    )
    return _me(refreshed)


@router.get("/csrf", response_model=CsrfOut)
def csrf(
    response: Response,
    principal: AuthPrincipal = Depends(current_user_principal),
) -> CsrfOut:
    token = issue_csrf_token(response)
    return CsrfOut(csrf_token=token)


# ---------------------------------------------------------------------------
# OIDC
# ---------------------------------------------------------------------------


def _ui_redirect(path: str, **params: str) -> RedirectResponse:
    from urllib.parse import urlencode

    base = get_settings().ui_base_url
    query = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"{base}{path}{query}", status_code=302)


@router.get("/oidc/login")
def oidc_login(db: Session = Depends(get_db)) -> RedirectResponse:
    if not oidc.enabled():
        raise HTTPException(status_code=404, detail="OIDC não configurado")
    try:
        url, cookie = oidc.begin_login(db)
    except oidc.OidcError as exc:
        return _ui_redirect("/login", oidc_error=str(exc))
    response = RedirectResponse(url, status_code=302)
    response.set_cookie(
        oidc.STATE_COOKIE,
        cookie,
        max_age=oidc.STATE_MAX_AGE_S,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        path="/api/v1/auth/oidc",
    )
    return response


@router.get("/oidc/callback")
def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not oidc.enabled():
        raise HTTPException(status_code=404, detail="OIDC não configurado")
    if error:
        return _ui_redirect(
            "/login", oidc_error=error_description or error or "falha no provedor"
        )
    cookie = request.cookies.get(oidc.STATE_COOKIE)
    if not cookie or not code or not state:
        return _ui_redirect("/login", oidc_error="retorno OIDC incompleto")
    try:
        payload = oidc.decode_state(cookie)
        if payload.get("state") != state:
            raise oidc.OidcError("state OIDC não confere")
        provider = db.get(IdentityProvider, payload.get("provider_id"))
        if provider is None or not provider.enabled:
            raise oidc.OidcError("provedor OIDC indisponível")
        tokens = oidc.exchange_code(
            provider,
            code,
            payload.get("verifier", ""),
            payload.get("redirect_uri", get_settings().oidc_callback_url),
        )
        claims = oidc.validate_id_token(provider, tokens["id_token"], payload["nonce"])
        user, membership, organization = oidc.resolve_user(db, provider, claims)
    except oidc.OidcAccessDenied as exc:
        log_audit(
            db,
            organization_id=None,
            action="auth.oidc_denied",
            metadata={"reason": str(exc)},
            request=request,
            commit=True,
        )
        return _ui_redirect("/login", oidc_error=str(exc))
    except oidc.OidcError as exc:
        log_audit(
            db,
            organization_id=None,
            action="auth.oidc_failed",
            metadata={"reason": str(exc)},
            request=request,
            commit=True,
        )
        return _ui_redirect("/login", oidc_error=str(exc))

    session, token, csrf = _create_session(
        db,
        request,
        user,
        auth_method="oidc",
        identity_provider_id=provider.id,
    )
    session.active_organization_id = organization.id
    db.commit()
    log_audit(
        db,
        organization_id=organization.id,
        actor_user_id=user.id,
        action="auth.oidc_login",
        resource_type="session",
        resource_id=session.id,
        metadata={"provider": provider.issuer},
        request=request,
        commit=True,
    )
    response = _ui_redirect("/")
    set_session_cookies(response, token, csrf)
    response.delete_cookie(
        oidc.STATE_COOKIE, path="/api/v1/auth/oidc"
    )
    return response


# ---------------------------------------------------------------------------
# Invitations
# ---------------------------------------------------------------------------


def _pending_invitation(db: Session, token: str) -> tuple[Invitation, Organization]:
    invitation = (
        db.query(Invitation)
        .filter(Invitation.token_hash == hash_token(token))
        .one_or_none()
    )
    if invitation is None or invitation.accepted_at is not None:
        raise HTTPException(status_code=404, detail="convite não encontrado")
    from ..security import ensure_utc

    expires = ensure_utc(invitation.expires_at)
    if expires is not None and expires <= utcnow():
        raise HTTPException(status_code=410, detail="convite expirado")
    organization = db.get(Organization, invitation.organization_id)
    if organization is None or organization.status != "active":
        raise HTTPException(status_code=404, detail="organização indisponível")
    return invitation, organization


@router.get("/invitations/{token}", response_model=InvitationInfoOut)
def invitation_info(token: str, db: Session = Depends(get_db)) -> InvitationInfoOut:
    invitation, organization = _pending_invitation(db, token)
    groups = (
        db.query(PermissionGroup)
        .filter(
            PermissionGroup.organization_id == organization.id,
            PermissionGroup.id.in_(invitation.group_ids or []),
        )
        .all()
        if invitation.group_ids
        else []
    )
    user = db.query(User).filter(User.email == invitation.email).one_or_none()
    return InvitationInfoOut(
        organization_name=organization.name,
        organization_slug=organization.slug,
        email=invitation.email,
        expires_at=invitation.expires_at,
        groups=[group.name for group in groups],
        requires_password=user is None or not user.password_hash,
    )


@router.post("/invitations/accept", response_model=MeOut)
def accept_invitation(
    payload: InvitationAcceptRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> MeOut:
    invitation, organization = _pending_invitation(db, payload.token)
    email = normalize_email(invitation.email)
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None:
        if not payload.password:
            raise HTTPException(status_code=422, detail="senha obrigatória para criar a conta")
        user = User(
            email=email,
            display_name=(payload.display_name or email.split("@")[0])[:200],
            password_hash=hash_password(payload.password),
            email_verified_at=utcnow(),
            is_active=True,
        )
        db.add(user)
        db.flush()
    elif not user.password_hash:
        if not payload.password:
            raise HTTPException(status_code=422, detail="defina uma senha para sua conta")
        user.password_hash = hash_password(payload.password)
    if payload.display_name:
        user.display_name = payload.display_name[:200]
    if not user.is_active:
        raise HTTPException(status_code=403, detail="usuário desativado")

    membership = (
        db.query(Membership)
        .filter(
            Membership.user_id == user.id,
            Membership.organization_id == organization.id,
        )
        .one_or_none()
    )
    if membership is None:
        membership = Membership(
            user_id=user.id,
            organization_id=organization.id,
            status="active",
        )
        db.add(membership)
        db.flush()
    groups = (
        db.query(PermissionGroup)
        .filter(
            PermissionGroup.organization_id == organization.id,
            PermissionGroup.id.in_(invitation.group_ids or []),
        )
        .all()
        if invitation.group_ids
        else []
    )
    if groups:
        membership.permission_groups = groups
    membership.status = "active"
    invitation.accepted_at = utcnow()
    invitation.accepted_by_user_id = user.id
    db.commit()
    log_audit(
        db,
        organization_id=organization.id,
        actor_user_id=user.id,
        action="invitation.accept",
        resource_type="invitation",
        resource_id=invitation.id,
        request=request,
        commit=True,
    )

    session, token, csrf = _create_session(db, request, user)
    session.active_organization_id = organization.id
    db.commit()
    set_session_cookies(response, token, csrf)
    principal = AuthPrincipal(
        user=user,
        session=session,
        organization=organization,
        membership=membership,
        permissions=effective_permissions(membership),
    )
    return _me(principal)
