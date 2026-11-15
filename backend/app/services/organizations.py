from __future__ import annotations

import re
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from ..models import (
    CameraProfile,
    Invitation,
    Membership,
    Organization,
    PermissionGroup,
    PrivacySettings,
    User,
    new_id,
    utcnow,
)
from ..permissions import ROLE_TEMPLATES
from ..security import hash_password, hash_token, normalize_email
from ..tenancy import log_audit


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug[:60] or "org"


def unique_slug(db: Session, base: str) -> str:
    slug = slugify(base)
    candidate = slug
    counter = 1
    while db.query(Organization).filter(Organization.slug == candidate).first():
        counter += 1
        candidate = f"{slug}-{counter}"[:80]
    return candidate


def create_default_groups(db: Session, organization_id: str) -> dict[str, PermissionGroup]:
    groups: dict[str, PermissionGroup] = {}
    for name, template in ROLE_TEMPLATES.items():
        group = PermissionGroup(
            organization_id=organization_id,
            name=name,
            description=str(template["description"]),
            permissions=list(template["permissions"]),  # type: ignore[arg-type]
            is_system=bool(template["is_system"]),
        )
        db.add(group)
        groups[name] = group
    db.flush()
    return groups


def attach_groups(
    db: Session, membership: Membership, groups: list[PermissionGroup]
) -> None:
    membership.permission_groups = groups
    db.flush()


def create_owner_membership(
    db: Session, *, user: User, organization: Organization
) -> Membership:
    groups = create_default_groups(db, organization.id)
    membership = Membership(
        user_id=user.id,
        organization_id=organization.id,
        status="active",
    )
    db.add(membership)
    db.flush()
    attach_groups(db, membership, [groups["Owner"]])
    db.add(PrivacySettings(organization_id=organization.id))
    db.add(
        CameraProfile(
            organization_id=organization.id,
            name="Default",
            masks=[],
            roi=None,
            settings={},
        )
    )
    return membership


def setup_required(db: Session) -> bool:
    return db.query(Organization).count() == 0


def create_organization_with_owner(
    db: Session,
    *,
    organization_name: str,
    slug: str | None,
    owner_email: str,
    owner_password: str,
    owner_display_name: str,
    request=None,
) -> tuple[Organization, User, Membership]:
    email = normalize_email(owner_email)
    if db.query(User).filter(User.email == email).first():
        raise ValueError("já existe um usuário com esse e-mail")
    organization = Organization(
        name=organization_name.strip(),
        slug=unique_slug(db, slug or organization_name),
        status="active",
    )
    user = User(
        email=email,
        display_name=(owner_display_name or email.split("@")[0])[:200],
        password_hash=hash_password(owner_password),
        is_platform_admin=True,
        is_active=True,
        email_verified_at=utcnow(),
    )
    db.add_all([organization, user])
    db.flush()
    membership = create_owner_membership(db, user=user, organization=organization)
    log_audit(
        db,
        organization_id=organization.id,
        actor_user_id=user.id,
        action="organization.create",
        resource_type="organization",
        resource_id=organization.id,
        metadata={"slug": organization.slug, "source": "setup"},
        request=request,
    )
    db.commit()
    db.refresh(organization)
    db.refresh(user)
    db.refresh(membership)
    return organization, user, membership


def create_invitation(
    db: Session,
    *,
    organization: Organization,
    email: str,
    group_ids: list[str],
    invited_by: User,
    ttl_hours: int = 168,
) -> tuple[Invitation, str]:
    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        organization_id=organization.id,
        email=normalize_email(email),
        token_hash=hash_token(token),
        group_ids=group_ids,
        invited_by_user_id=invited_by.id,
        expires_at=utcnow() + timedelta(hours=ttl_hours),
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return invitation, token


def invite_or_activate_member(
    db: Session,
    *,
    organization: Organization,
    email: str,
    group_ids: list[str],
    invited_by: User,
    request=None,
) -> tuple[Membership, str | None]:
    """Create a pending membership and an invitation token.

    The invited user sets a password when accepting; until then the membership
    is ``invited`` and grants no access.
    """
    normalized = normalize_email(email)
    user = db.query(User).filter(User.email == normalized).one_or_none()
    if user is None:
        user = User(
            email=normalized,
            display_name=normalized.split("@")[0][:200],
            is_active=True,
        )
        db.add(user)
        db.flush()
    membership = (
        db.query(Membership)
        .filter(
            Membership.user_id == user.id,
            Membership.organization_id == organization.id,
        )
        .one_or_none()
    )
    if membership is not None and membership.status == "active":
        raise ValueError("usuário já é membro ativo")
    if membership is None:
        membership = Membership(
            user_id=user.id,
            organization_id=organization.id,
            status="invited",
        )
        db.add(membership)
        db.flush()
    groups = (
        db.query(PermissionGroup)
        .filter(
            PermissionGroup.organization_id == organization.id,
            PermissionGroup.id.in_(group_ids),
        )
        .all()
        if group_ids
        else []
    )
    if groups:
        attach_groups(db, membership, groups)
    invitation, token = create_invitation(
        db,
        organization=organization,
        email=normalized,
        group_ids=[group.id for group in groups],
        invited_by=invited_by,
    )
    log_audit(
        db,
        organization_id=organization.id,
        actor_user_id=invited_by.id,
        action="member.invite",
        resource_type="membership",
        resource_id=membership.id,
        metadata={"email": normalized, "groups": [g.name for g in groups]},
        request=request,
        commit=True,
    )
    return membership, token


def generate_protocol() -> str:
    return f"DSR-{utcnow():%Y%m%d}-{new_id()[:8].upper()}"
