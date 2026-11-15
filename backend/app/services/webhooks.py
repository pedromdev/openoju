from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import socket
import time
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import WebhookEndpoint, utcnow
from ..security import decrypt_secret, encrypt_secret

BACKOFF_SCHEDULE = [60, 300, 1800, 7200, 21600]
BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata",
}


class WebhookUrlError(ValueError):
    pass


def _blocked_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return True
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def validate_webhook_url(url: str) -> None:
    settings = get_settings()
    parsed = urlparse(url)
    allowed_schemes = {"https"} | ({"http"} if settings.webhook_allow_http else set())
    if parsed.scheme not in allowed_schemes:
        raise WebhookUrlError("webhook exige HTTPS")
    if not parsed.hostname:
        raise WebhookUrlError("webhook sem host")
    if parsed.username or parsed.password:
        raise WebhookUrlError("webhook não pode conter credenciais na URL")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in BLOCKED_HOSTNAMES or hostname.endswith(".local") or hostname.endswith(".internal"):
        raise WebhookUrlError("host de webhook não permitido")
    try:
        direct = ipaddress.ip_address(hostname)
        if _blocked_ip(str(direct)):
            raise WebhookUrlError("IP de webhook não permitido")
        return
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise WebhookUrlError(f"não foi possível resolver o host: {exc}") from exc
    if not infos:
        raise WebhookUrlError("host de webhook sem resolução")
    for info in infos:
        address = info[4][0]
        if _blocked_ip(address):
            raise WebhookUrlError(f"webhook resolve para IP não permitido: {address}")


def new_webhook_secret() -> str:
    import secrets

    return "whsec_" + secrets.token_urlsafe(32)


def store_secret(secret: str) -> str:
    return encrypt_secret(secret)


def load_secret(endpoint: WebhookEndpoint) -> str:
    return decrypt_secret(endpoint.secret_encrypted)


def sign(secret: str, timestamp: int, body: str) -> str:
    message = f"{timestamp}.{body}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def signature_header(secret: str, timestamp: int, body: str) -> str:
    return f"sha256={sign(secret, timestamp, body)}"


def serialize_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def delivery_headers(
    *, event_type: str, delivery_id: str, secret: str, body: str
) -> dict[str, str]:
    timestamp = int(time.time())
    return {
        "Content-Type": "application/json",
        "User-Agent": "CameraAnomaly-Webhook/1.0",
        "X-Camera-Event": event_type,
        "X-Camera-Delivery": delivery_id,
        "X-Camera-Timestamp": str(timestamp),
        "X-Camera-Signature": signature_header(secret, timestamp, body),
    }


def next_attempt(attempts: int):
    index = min(max(attempts - 1, 0), len(BACKOFF_SCHEDULE) - 1)
    return utcnow() + timedelta(seconds=BACKOFF_SCHEDULE[index])


def endpoint_subscribed(endpoint: WebhookEndpoint, event_type: str) -> bool:
    events = endpoint.events or []
    return not events or event_type in events or "*" in events


def fan_out(db: Session, limit: int = 50) -> int:
    from ..models import OutboxEvent, WebhookDelivery

    events = (
        db.query(OutboxEvent)
        .filter(OutboxEvent.processed_at.is_(None))
        .order_by(OutboxEvent.created_at.asc())
        .limit(limit)
        .all()
    )
    created = 0
    for event in events:
        endpoints = (
            db.query(WebhookEndpoint)
            .filter(
                WebhookEndpoint.organization_id == event.organization_id,
                WebhookEndpoint.active.is_(True),
            )
            .all()
        )
        for endpoint in endpoints:
            if not endpoint_subscribed(endpoint, event.type):
                continue
            payload = {
                "type": event.type,
                "id": event.id,
                "created_at": event.created_at.isoformat() if event.created_at else None,
                "data": event.payload,
            }
            db.add(
                WebhookDelivery(
                    organization_id=event.organization_id,
                    endpoint_id=endpoint.id,
                    outbox_event_id=event.id,
                    event_type=event.type,
                    payload=payload,
                    status="pending",
                    attempts=0,
                    next_attempt_at=utcnow(),
                )
            )
            created += 1
        event.processed_at = utcnow()
    db.commit()
    return created
