from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import OutboxEvent


def emit(
    db: Session,
    *,
    organization_id: str,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    payload: dict[str, Any],
) -> OutboxEvent:
    """Write a lifecycle event to the transactional outbox.

    The webhook dispatcher (phase 6) consumes these rows. Emitting inside the
    same transaction as the domain change guarantees at-least-once delivery.
    """
    event = OutboxEvent(
        organization_id=organization_id,
        type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
    )
    db.add(event)
    return event
