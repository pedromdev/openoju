from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from authlib.jose import JsonWebKey, jwt
from fastapi import HTTPException
from sqlalchemy.orm import Session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import Settings, get_settings
from .models import (
    IdentityProvider,
    Invitation,
    Membership,
    Organization,
    PermissionGroup,
    User,
    UserIdentity,
)
from .security import (
    decrypt_secret,
    encrypt_secret,
    ensure_utc,
    normalize_email,
    utcnow as now,
)

STATE_COOKIE = "openoju_oidc_state"
STATE_MAX_AGE_S = 600
_CACHE_TTL_S = 300
_discovery_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_jwks_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class OidcError(RuntimeError):
    pass


class OidcAccessDenied(OidcError):
    pass


def enabled(settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    return bool(
        settings.oidc_enabled
        and settings.oidc_issuer
        and settings.oidc_client_id
        and settings.oidc_client_secret
    )


def _serializer() -> URLSafeTimedSerializer:
    settings = get_settings()
    if not settings.secret_key:
        raise RuntimeError("OJU_SECRET_KEY é obrigatório para OIDC")
    return URLSafeTimedSerializer(settings.secret_key, salt="camera-oidc-state")


def encode_state(payload: dict[str, Any]) -> str:
    return _serializer().dumps(payload)


def decode_state(value: str) -> dict[str, Any]:
    try:
        return _serializer().loads(value, max_age=STATE_MAX_AGE_S)
    except SignatureExpired as exc:
        raise OidcError("estado OIDC expirado") from exc
    except BadSignature as exc:
        raise OidcError("estado OIDC inválido") from exc


def get_discovery(issuer: str) -> dict[str, Any]:
    cached = _discovery_cache.get(issuer)
    if cached and time.time() - cached[0] < _CACHE_TTL_S:
        return cached[1]
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        response = httpx.get(url, timeout=10.0, follow_redirects=True)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcError(f"falha ao carregar discovery OIDC: {exc}") from exc
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not data.get(key):
            raise OidcError(f"discovery OIDC sem {key}")
    _discovery_cache[issuer] = (time.time(), data)
    return data


def get_jwks(issuer: str) -> dict[str, Any]:
    cached = _jwks_cache.get(issuer)
    if cached and time.time() - cached[0] < _CACHE_TTL_S:
        return cached[1]
    discovery = get_discovery(issuer)
    try:
        response = httpx.get(discovery["jwks_uri"], timeout=10.0)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcError(f"falha ao carregar JWKS: {exc}") from exc
    _jwks_cache[issuer] = (time.time(), data)
    return data


def ensure_provider(db: Session) -> IdentityProvider:
    settings = get_settings()
    provider = (
        db.query(IdentityProvider)
        .filter(IdentityProvider.issuer == settings.oidc_issuer)
        .one_or_none()
    )
    if provider is None:
        provider = IdentityProvider(
            organization_id=None,
            name="OIDC institucional",
            type="oidc",
            issuer=settings.oidc_issuer,
            client_id=settings.oidc_client_id,
            client_secret_encrypted=encrypt_secret(settings.oidc_client_secret),
            scopes=settings.oidc_scopes,
            enabled=True,
            auto_provision=settings.oidc_auto_provision,
            default_group_id=None,
        )
        db.add(provider)
        db.commit()
        db.refresh(provider)
    return provider


def begin_login(db: Session) -> tuple[str, str]:
    settings = get_settings()
    provider = ensure_provider(db)
    discovery = get_discovery(provider.issuer)
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": provider.client_id,
        "redirect_uri": settings.oidc_callback_url,
        "scope": provider.scopes or "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = discovery["authorization_endpoint"] + "?" + urlencode(params)
    cookie = encode_state(
        {
            "state": state,
            "nonce": nonce,
            "verifier": verifier,
            "redirect_uri": settings.oidc_callback_url,
            "provider_id": provider.id,
        }
    )
    return url, cookie


def exchange_code(provider: IdentityProvider, code: str, verifier: str, redirect_uri: str) -> dict[str, Any]:
    discovery = get_discovery(provider.issuer)
    secret = (
        decrypt_secret(provider.client_secret_encrypted)
        if provider.client_secret_encrypted
        else get_settings().oidc_client_secret
    )
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": provider.client_id,
        "client_secret": secret,
        "code_verifier": verifier,
    }
    try:
        response = httpx.post(discovery["token_endpoint"], data=data, timeout=15.0)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcError(f"falha na troca de token OIDC: {exc}") from exc
    if "id_token" not in payload:
        raise OidcError("resposta OIDC sem id_token")
    return payload


def validate_id_token(provider: IdentityProvider, id_token: str, nonce: str) -> dict[str, Any]:
    key_set = JsonWebKey.import_key_set(get_jwks(provider.issuer))
    try:
        claims = jwt.decode(id_token, key_set)
        claims.validate()
    except Exception as exc:  # noqa: BLE001 - authlib raises several types
        raise OidcError(f"id_token inválido: {exc}") from exc
    if claims.get("iss") != provider.issuer:
        raise OidcError("issuer do id_token não confere")
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if provider.client_id not in audiences:
        raise OidcError("audience do id_token não confere")
    if claims.get("nonce") != nonce:
        raise OidcError("nonce do id_token não confere")
    return dict(claims)


def _find_invitation(db: Session, email: str, organization_id: str | None = None) -> Invitation | None:
    query = db.query(Invitation).filter(
        Invitation.email == email,
        Invitation.accepted_at.is_(None),
    )
    if organization_id:
        query = query.filter(Invitation.organization_id == organization_id)
    for invitation in query.order_by(Invitation.created_at.asc()).all():
        expires = ensure_utc(invitation.expires_at)
        if expires is not None and expires > now():
            return invitation
    return None


def _activate_invitation(db: Session, user: User, invitation: Invitation) -> Membership:
    membership = (
        db.query(Membership)
        .filter(
            Membership.user_id == user.id,
            Membership.organization_id == invitation.organization_id,
        )
        .one_or_none()
    )
    if membership is None:
        membership = Membership(
            user_id=user.id,
            organization_id=invitation.organization_id,
            status="active",
        )
        db.add(membership)
        db.flush()
    groups = (
        db.query(PermissionGroup)
        .filter(
            PermissionGroup.organization_id == invitation.organization_id,
            PermissionGroup.id.in_(invitation.group_ids or []),
        )
        .all()
        if invitation.group_ids
        else []
    )
    if not groups:
        viewer = (
            db.query(PermissionGroup)
            .filter(
                PermissionGroup.organization_id == invitation.organization_id,
                PermissionGroup.name == get_settings().oidc_default_group,
            )
            .one_or_none()
        )
        groups = [viewer] if viewer else []
    membership.status = "active"
    membership.permission_groups = groups
    invitation.accepted_at = now()
    invitation.accepted_by_user_id = user.id
    db.flush()
    return membership


def _resolve_target_org(
    db: Session, provider: IdentityProvider, invitation: Invitation | None
) -> Organization | None:
    if invitation is not None:
        return db.get(Organization, invitation.organization_id)
    if provider.organization_id:
        return db.get(Organization, provider.organization_id)
    organizations = db.query(Organization).filter(Organization.status == "active").all()
    if len(organizations) == 1:
        return organizations[0]
    return None


def resolve_user(
    db: Session, provider: IdentityProvider, claims: dict[str, Any]
) -> tuple[User, Membership, Organization]:
    subject = str(claims.get("sub") or "")
    if not subject:
        raise OidcError("id_token sem subject")
    email = normalize_email(str(claims.get("email") or ""))
    if not email:
        raise OidcAccessDenied("provedor não retornou e-mail")
    email_verified = bool(claims.get("email_verified"))
    display_name = str(claims.get("name") or claims.get("preferred_username") or email.split("@")[0])[:200]

    identity = (
        db.query(UserIdentity)
        .filter(
            UserIdentity.provider_id == provider.id,
            UserIdentity.subject == subject,
        )
        .one_or_none()
    )
    user: User | None = identity.user if identity is not None else None
    organization: Organization | None = None
    membership: Membership | None = None

    if user is None:
        user = db.query(User).filter(User.email == email).one_or_none()
        invitation = _find_invitation(db, email)
        if user is None:
            if invitation is not None:
                user = User(
                    email=email,
                    display_name=display_name,
                    is_active=True,
                    email_verified_at=now() if email_verified else None,
                )
                db.add(user)
                db.flush()
            elif provider.auto_provision:
                target = _resolve_target_org(db, provider, invitation)
                if target is None:
                    raise OidcAccessDenied(
                        "auto-provisionamento exige uma organização definida"
                    )
                user = User(
                    email=email,
                    display_name=display_name,
                    is_active=True,
                    email_verified_at=now() if email_verified else None,
                )
                db.add(user)
                db.flush()
            else:
                raise OidcAccessDenied(
                    "usuário sem convite; peça acesso a um administrador"
                )

    if not user.is_active:
        raise OidcAccessDenied("usuário desativado")

    if identity is None:
        if user.email != email and not email_verified:
            raise OidcAccessDenied("conta existente com e-mail diferente não verificado")
        identity = UserIdentity(
            user_id=user.id,
            provider_id=provider.id,
            subject=subject,
            email_at_provider=email,
            claims={
                "email": email,
                "name": claims.get("name"),
                "preferred_username": claims.get("preferred_username"),
            },
        )
        db.add(identity)
    else:
        identity.email_at_provider = email
    identity.last_login_at = now()
    user.last_login_at = now()

    membership = (
        db.query(Membership)
        .filter(Membership.user_id == user.id, Membership.status == "active")
        .order_by(Membership.created_at.asc())
        .first()
    )
    if membership is not None:
        organization = db.get(Organization, membership.organization_id)
    else:
        invitation = _find_invitation(db, email)
        if invitation is not None:
            membership = _activate_invitation(db, user, invitation)
            organization = db.get(Organization, membership.organization_id)
        elif provider.auto_provision:
            target = _resolve_target_org(db, provider, invitation)
            if target is None:
                raise OidcAccessDenied("sem organização ativa para provisionar")
            group = (
                db.query(PermissionGroup)
                .filter(
                    PermissionGroup.organization_id == target.id,
                    PermissionGroup.name == get_settings().oidc_default_group,
                )
                .one_or_none()
            )
            membership = Membership(
                user_id=user.id,
                organization_id=target.id,
                status="active",
            )
            db.add(membership)
            db.flush()
            if group is not None:
                membership.permission_groups = [group]
            organization = target

    if membership is None or organization is None:
        raise OidcAccessDenied(
            "sem acesso ativo; peça um convite ao administrador da organização"
        )
    if organization.status != "active":
        raise OidcAccessDenied("organização suspensa")

    db.commit()
    return user, membership, organization
