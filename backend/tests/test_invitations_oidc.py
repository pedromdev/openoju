from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import csrf_headers, login, setup_org


def test_invitation_accept_creates_local_account(client: TestClient) -> None:
    setup_org(client)
    invited = client.post(
        "/api/v1/orgs/acme/members/invite",
        json={"email": "novo@acme.com", "group_ids": []},
        headers=csrf_headers(client),
    )
    assert invited.status_code == 201, invited.text
    token = invited.json()["token"]

    info = client.get(f"/api/v1/auth/invitations/{token}")
    assert info.status_code == 200
    assert info.json()["organization_slug"] == "acme"
    assert info.json()["email"] == "novo@acme.com"

    with TestClient(client.app) as invited_client:
        accepted = invited_client.post(
            "/api/v1/auth/invitations/accept",
            json={
                "token": token,
                "password": "outra-senha-segura",
                "display_name": "Novo Membro",
            },
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["organization"]["slug"] == "acme"
        assert accepted.json()["user"]["email"] == "novo@acme.com"

        me = invited_client.get("/api/v1/auth/me")
        assert me.status_code == 200

    repeated = client.post(
        "/api/v1/auth/invitations/accept",
        json={"token": token, "password": "outra-senha-segura"},
    )
    assert repeated.status_code == 404


def test_invitation_requires_password_for_new_user(client: TestClient) -> None:
    setup_org(client)
    invited = client.post(
        "/api/v1/orgs/acme/members/invite",
        json={"email": "sem-senha@acme.com"},
        headers=csrf_headers(client),
    )
    token = invited.json()["token"]
    response = client.post("/api/v1/auth/invitations/accept", json={"token": token})
    assert response.status_code == 422


def test_oidc_resolution_requires_membership_or_invitation(client: TestClient) -> None:
    setup_org(client)
    from app import oidc
    from app.db import SessionLocal
    from app.models import IdentityProvider, Organization
    from app.security import encrypt_secret

    db = SessionLocal()
    try:
        organization = db.query(Organization).filter(Organization.slug == "acme").one()
        provider = IdentityProvider(
            organization_id=None,
            name="Teste OIDC",
            issuer="https://idp.example.com/realms/test",
            client_id="camera",
            client_secret_encrypted=encrypt_secret("segredo"),
            scopes="openid email profile",
            enabled=True,
            auto_provision=False,
        )
        db.add(provider)
        db.commit()
        db.refresh(provider)
        provider_id = provider.id
        org_id = organization.id

        claims = {
            "sub": "subject-1",
            "email": "sso@acme.com",
            "email_verified": True,
            "name": "SSO User",
        }
        try:
            oidc.resolve_user(db, provider, claims)
            raise AssertionError("deveria negar usuário sem convite")
        except oidc.OidcAccessDenied:
            pass

        # Invitation by e-mail enables the SSO account.
        from app.models import User
        from app.services.organizations import invite_or_activate_member

        inviter = db.query(User).filter_by(email="owner@acme.com").one()
        invite_or_activate_member(
            db,
            organization=organization,
            email="sso@acme.com",
            group_ids=[],
            invited_by=inviter,
        )
        user, membership, resolved_org = oidc.resolve_user(db, provider, claims)
        assert user.email == "sso@acme.com"
        assert membership.status == "active"
        assert resolved_org.id == org_id
        assert membership.organization_id == org_id
    finally:
        db.close()
