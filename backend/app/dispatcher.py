from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal
from .models import WebhookDelivery, WebhookEndpoint, utcnow
from .services.webhooks import (
    delivery_headers,
    fan_out,
    load_secret,
    next_attempt,
    serialize_payload,
    validate_webhook_url,
    WebhookUrlError,
)

logger = logging.getLogger("openoju.dispatcher")
_stop = threading.Event()


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def deliver(db: Session, delivery: WebhookDelivery, *, endpoint: WebhookEndpoint | None = None) -> WebhookDelivery:
    settings = get_settings()
    endpoint = endpoint or db.get(WebhookEndpoint, delivery.endpoint_id)
    if endpoint is None:
        delivery.status = "failed"
        delivery.response_body = "endpoint removido"
        db.commit()
        return delivery
    if not endpoint.active:
        delivery.status = "failed"
        delivery.response_body = "endpoint inativo"
        db.commit()
        return delivery
    try:
        validate_webhook_url(endpoint.url)
        secret = load_secret(endpoint)
    except (WebhookUrlError, ValueError) as exc:
        delivery.status = "failed"
        delivery.response_body = f"URL bloqueada: {exc}"[:4000]
        delivery.attempts += 1
        db.commit()
        return delivery

    body = serialize_payload(delivery.payload)
    headers = delivery_headers(
        event_type=delivery.event_type,
        delivery_id=delivery.id,
        secret=secret,
        body=body,
    )
    started = time.monotonic()
    try:
        response = httpx.post(
            endpoint.url,
            content=body,
            headers=headers,
            timeout=settings.webhook_timeout_s,
            follow_redirects=False,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        delivery.attempts += 1
        delivery.response_status = response.status_code
        delivery.response_body = response.text[:4000]
        delivery.duration_ms = duration_ms
        if 200 <= response.status_code < 300:
            delivery.status = "success"
            delivery.delivered_at = utcnow()
            delivery.next_attempt_at = None
            endpoint.last_success_at = utcnow()
            endpoint.failure_count = 0
        else:
            delivery.status = (
                "failed" if delivery.attempts >= settings.webhook_max_attempts else "pending"
            )
            delivery.next_attempt_at = (
                None
                if delivery.status == "failed"
                else next_attempt(delivery.attempts)
            )
            endpoint.failure_count += 1
    except httpx.HTTPError as exc:
        delivery.attempts += 1
        delivery.response_status = None
        delivery.response_body = str(exc)[:4000]
        delivery.duration_ms = int((time.monotonic() - started) * 1000)
        delivery.status = (
            "failed" if delivery.attempts >= settings.webhook_max_attempts else "pending"
        )
        delivery.next_attempt_at = (
            None if delivery.status == "failed" else next_attempt(delivery.attempts)
        )
        endpoint.failure_count += 1
    db.commit()
    return delivery


def run_once() -> tuple[int, int]:
    settings = get_settings()
    db = SessionLocal()
    try:
        fanned = fan_out(db, limit=settings.dispatcher_batch_size)
    finally:
        db.close()
    db = SessionLocal()
    delivered = 0
    try:
        now = utcnow()
        candidates = (
            db.query(WebhookDelivery)
            .filter(
                WebhookDelivery.status.in_(["pending", "failed"]),
                WebhookDelivery.attempts < settings.webhook_max_attempts,
            )
            .order_by(WebhookDelivery.created_at.asc())
            .limit(settings.dispatcher_batch_size)
            .all()
        )
        for delivery in candidates:
            due = _naive_utc(delivery.next_attempt_at)
            if due is not None and due > now:
                continue
            deliver(db, delivery)
            delivered += 1
    finally:
        db.close()
    return fanned, delivered


def _signal_handler(signum, _frame) -> None:  # type: ignore[no-untyped-def]
    logger.info("sinal %s recebido; encerrando", signum)
    _stop.set()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    logger.info("dispatcher iniciado")
    while not _stop.is_set():
        try:
            fanned, delivered = run_once()
            if fanned or delivered:
                logger.info("outbox=%s entregas=%s", fanned, delivered)
        except Exception as exc:  # noqa: BLE001 - dispatcher must stay alive
            logger.exception("erro no dispatcher: %s", exc)
        _stop.wait(settings.dispatcher_interval_s)
    logger.info("dispatcher encerrado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
