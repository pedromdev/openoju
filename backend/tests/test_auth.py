from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import csrf_headers, login, setup_org


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_setup_flow_and_single_use(client: TestClient) -> None:
    status_response = client.get("/api/v1/auth/setup/status")
    assert status_response.status_code == 200
    assert status_response.json()["setup_required"] is True

    wrong = client.post(
        "/api/v1/auth/setup",
        json={
            "token": "wrong-token",
            "organization_name": "Acme",
            "owner_email": "owner@acme.com",
            "owner_password": "senha-muito-segura",
        },
    )
    assert wrong.status_code == 403

    me = setup_org(client)
    assert me["organization"]["slug"] == "acme"
    assert "organization.view" in me["permissions"]
    assert [group["name"] for group in me["groups"]] == ["Owner"]

    assert client.get("/api/v1/auth/setup/status").json()["setup_required"] is False

    again = client.post(
        "/api/v1/auth/setup",
        json={
            "token": "test-setup-token",
            "organization_name": "Outra",
            "owner_email": "other@acme.com",
            "owner_password": "senha-muito-segura",
        },
    )
    assert again.status_code == 409


def test_login_logout_and_revocation(client: TestClient) -> None:
    setup_org(client)
    logout = client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    assert logout.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401

    response = login(client, "owner@acme.com", "senha-muito-segura")
    assert response.status_code == 200
    assert response.json()["user"]["email"] == "owner@acme.com"
    assert client.get("/api/v1/auth/me").status_code == 200

    logout_all = client.post("/api/v1/auth/logout-all", headers=csrf_headers(client))
    assert logout_all.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_wrong_password_is_rejected(client: TestClient) -> None:
    setup_org(client)
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    response = login(client, "owner@acme.com", "senha-errada")
    assert response.status_code == 401


def test_csrf_blocks_mutations(client: TestClient) -> None:
    setup_org(client)
    payload = {"name": "Portaria", "masks": [], "settings": {}}
    without = client.post("/api/v1/orgs/acme/profiles", json=payload)
    assert without.status_code == 403
    assert without.json()["detail"] == "CSRF token inválido"

    with_token = client.post(
        "/api/v1/orgs/acme/profiles", json=payload, headers=csrf_headers(client)
    )
    assert with_token.status_code == 201


def test_login_rate_limit(client: TestClient) -> None:
    setup_org(client)
    client.post("/api/v1/auth/logout", headers=csrf_headers(client))
    for _ in range(10):
        assert login(client, "owner@acme.com", "errada").status_code == 401
    blocked = login(client, "owner@acme.com", "senha-muito-segura")
    assert blocked.status_code == 429


def test_last_owner_cannot_be_suspended(client: TestClient) -> None:
    setup_org(client)
    members = client.get("/api/v1/orgs/acme/members").json()
    owner = next(member for member in members if member["email"] == "owner@acme.com")
    response = client.patch(
        f"/api/v1/orgs/acme/members/{owner['id']}",
        json={"status": "suspended"},
        headers=csrf_headers(client),
    )
    assert response.status_code == 409


def test_audit_log_records_setup(client: TestClient) -> None:
    setup_org(client)
    response = client.get("/api/v1/orgs/acme/audit")
    assert response.status_code == 200
    actions = {entry["action"] for entry in response.json()}
    assert "organization.create" in actions
