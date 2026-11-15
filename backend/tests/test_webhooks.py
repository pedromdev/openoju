from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import csrf_headers, setup_org


@pytest.fixture(autouse=True)
def allow_webhook_urls(monkeypatch):
    monkeypatch.setattr("app.api.webhooks.validate_webhook_url", lambda url: None)
    monkeypatch.setattr("app.dispatcher.validate_webhook_url", lambda url: None)


class FakeResponse:
    def __init__(self, status_code: int = 200, text: str = "ok") -> None:
        self.status_code = status_code
        self.text = text


def test_create_list_and_reveal_secret_once(client: TestClient) -> None:
    setup_org(client)
    created = client.post(
        "/api/v1/orgs/acme/webhooks",
        json={"name": "SIEM", "url": "https://example.com/hook", "events": ["event.created"]},
        headers=csrf_headers(client),
    )
    assert created.status_code == 201, created.text
    secret = created.json()["secret"]
    assert secret.startswith("whsec_")
    endpoint_id = created.json()["endpoint"]["id"]

    listing = client.get("/api/v1/orgs/acme/webhooks")
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == endpoint_id
    assert "secret" not in listing.json()[0]

    updated = client.put(
        f"/api/v1/orgs/acme/webhooks/{endpoint_id}",
        json={"name": "SIEM 2", "url": "https://example.com/hook2", "events": [], "active": True},
        headers=csrf_headers(client),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "SIEM 2"


def test_test_delivery_success_and_failure(
    client: TestClient, monkeypatch
) -> None:
    setup_org(client)
    created = client.post(
        "/api/v1/orgs/acme/webhooks",
        json={"name": "hook", "url": "https://example.com/hook", "events": ["*"]},
        headers=csrf_headers(client),
    )
    endpoint_id = created.json()["endpoint"]["id"]

    monkeypatch.setattr(
        "app.dispatcher.httpx.post", lambda *a, **k: FakeResponse(200, "ok")
    )
    tested = client.post(
        f"/api/v1/orgs/acme/webhooks/{endpoint_id}/test", headers=csrf_headers(client)
    )
    assert tested.status_code == 200, tested.text
    delivery = tested.json()["delivery"]
    assert delivery["status"] == "success"
    assert delivery["response_status"] == 200

    def boom(*args, **kwargs):
        raise httpx.ConnectError("falha de conexão")

    monkeypatch.setattr("app.dispatcher.httpx.post", boom)
    failed = client.post(
        f"/api/v1/orgs/acme/webhooks/{endpoint_id}/test", headers=csrf_headers(client)
    )
    assert failed.status_code == 200
    delivery = failed.json()["delivery"]
    assert delivery["status"] == "pending"
    assert delivery["attempts"] == 1
    assert delivery["next_attempt_at"] is not None

    retried = client.post(
        f"/api/v1/orgs/acme/webhooks/{endpoint_id}/deliveries/{delivery['id']}/retry",
        headers=csrf_headers(client),
    )
    assert retried.status_code == 200
    assert retried.json()["attempts"] == 0


def test_outbox_fan_out_only_to_subscribed_endpoints(client: TestClient) -> None:
    setup_org(client)
    client.post(
        "/api/v1/orgs/acme/webhooks",
        json={"name": "eventos", "url": "https://example.com/e", "events": ["event.created"]},
        headers=csrf_headers(client),
    )
    client.post(
        "/api/v1/orgs/acme/webhooks",
        json={"name": "analise", "url": "https://example.com/a", "events": ["analysis.completed"]},
        headers=csrf_headers(client),
    )

    from app.db import SessionLocal
    from app.models import Organization, OutboxEvent, WebhookDelivery
    from app.services.webhooks import fan_out

    db = SessionLocal()
    try:
        organization = db.query(Organization).filter(Organization.slug == "acme").one()
        db.add(
            OutboxEvent(
                organization_id=organization.id,
                type="event.created",
                aggregate_type="event",
                aggregate_id="evt-1",
                payload={"id": "evt-1"},
            )
        )
        db.commit()
        assert fan_out(db) == 1
        deliveries = db.query(WebhookDelivery).all()
        assert len(deliveries) == 1
        assert deliveries[0].event_type == "event.created"
    finally:
        db.close()


def test_signature_is_deterministic() -> None:
    from app.services.webhooks import signature_header, sign

    secret = "whsec_teste"
    body = '{"a":1}'
    first = sign(secret, 123, body)
    second = sign(secret, 123, body)
    assert first == second
    assert signature_header(secret, 123, body) == f"sha256={first}"


def test_ssrf_validator_blocks_internal_targets() -> None:
    from app.services.webhooks import WebhookUrlError, validate_webhook_url

    for url in (
        "http://example.com/hook",
        "https://127.0.0.1/hook",
        "https://localhost/hook",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.5/hook",
        "file:///etc/passwd",
    ):
        with pytest.raises(WebhookUrlError):
            validate_webhook_url(url)


def test_webhook_is_tenant_scoped(client: TestClient) -> None:
    setup_org(client)
    created = client.post(
        "/api/v1/orgs/acme/webhooks",
        json={"name": "hook", "url": "https://example.com/hook", "events": []},
        headers=csrf_headers(client),
    )
    endpoint_id = created.json()["endpoint"]["id"]

    from conftest import create_org, login

    create_org(name="Globex", slug="globex", email="owner@globex.com", password="senha-muito-segura")
    with TestClient(client.app) as other:
        login(other, "owner@globex.com", "senha-muito-segura")
        assert (
            other.post(
                f"/api/v1/orgs/globex/webhooks/{endpoint_id}/test",
                headers=csrf_headers(other),
            ).status_code
            == 404
        )
        assert other.get("/api/v1/orgs/acme/webhooks").status_code == 404
