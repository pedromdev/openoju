from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..auth import require_org
from ..db import get_db
from ..dispatcher import deliver
from ..models import OutboxEvent, WebhookDelivery, WebhookEndpoint, new_id, utcnow
from ..permissions import WEBHOOKS_MANAGE
from ..schemas import (
    WebhookDeliveryOut,
    WebhookEndpointCreatedOut,
    WebhookEndpointIn,
    WebhookEndpointOut,
    WebhookTestOut,
)
from ..services.webhooks import (
    WebhookUrlError,
    new_webhook_secret,
    store_secret,
    validate_webhook_url,
)
from ..tenancy import AuthPrincipal, log_audit, scoped_get, scoped_query

router = APIRouter(prefix="/orgs/{slug}/webhooks", tags=["webhooks"])

ALLOWED_EVENTS = {
    "event.created",
    "analysis.completed",
    "analysis.failed",
    "video.created",
}


def _validate_events(events: list[str]) -> list[str]:
    unknown = sorted(set(events) - ALLOWED_EVENTS - {"*"})
    if unknown:
        raise HTTPException(status_code=422, detail=f"eventos desconhecidos: {unknown}")
    return sorted(set(events))


def _validate_url(url: str) -> None:
    try:
        validate_webhook_url(url)
    except WebhookUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _endpoint(db: Session, organization_id: str, endpoint_id: str) -> WebhookEndpoint:
    return scoped_get(
        db, WebhookEndpoint, organization_id, endpoint_id, detail="webhook não encontrado"
    )


@router.get("", response_model=list[WebhookEndpointOut])
def list_endpoints(
    principal: AuthPrincipal = Depends(require_org(WEBHOOKS_MANAGE)),
    db: Session = Depends(get_db),
) -> list[WebhookEndpointOut]:
    endpoints = (
        scoped_query(db, WebhookEndpoint, principal.organization_id or "")
        .order_by(WebhookEndpoint.created_at.desc())
        .all()
    )
    return [WebhookEndpointOut.model_validate(endpoint) for endpoint in endpoints]


@router.post("", response_model=WebhookEndpointCreatedOut, status_code=201)
def create_endpoint(
    payload: WebhookEndpointIn,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(WEBHOOKS_MANAGE)),
    db: Session = Depends(get_db),
) -> WebhookEndpointCreatedOut:
    _validate_url(payload.url)
    events = _validate_events(payload.events)
    secret = new_webhook_secret()
    endpoint = WebhookEndpoint(
        organization_id=principal.organization_id or "",
        name=payload.name,
        url=payload.url,
        secret_encrypted=store_secret(secret),
        events=events,
        active=payload.active,
        created_by_user_id=principal.user_id,
    )
    db.add(endpoint)
    db.commit()
    db.refresh(endpoint)
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="webhook.create",
        resource_type="webhook_endpoint",
        resource_id=endpoint.id,
        metadata={"url": endpoint.url, "events": events},
        request=request,
        commit=True,
    )
    return WebhookEndpointCreatedOut(
        endpoint=WebhookEndpointOut.model_validate(endpoint), secret=secret
    )


@router.put("/{endpoint_id}", response_model=WebhookEndpointOut)
def update_endpoint(
    endpoint_id: str,
    payload: WebhookEndpointIn,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(WEBHOOKS_MANAGE)),
    db: Session = Depends(get_db),
) -> WebhookEndpointOut:
    endpoint = _endpoint(db, principal.organization_id or "", endpoint_id)
    if payload.url != endpoint.url:
        _validate_url(payload.url)
    events = _validate_events(payload.events)
    endpoint.name = payload.name
    endpoint.url = payload.url
    endpoint.events = events
    endpoint.active = payload.active
    db.commit()
    db.refresh(endpoint)
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="webhook.update",
        resource_type="webhook_endpoint",
        resource_id=endpoint.id,
        metadata={"url": endpoint.url, "events": events, "active": endpoint.active},
        request=request,
        commit=True,
    )
    return WebhookEndpointOut.model_validate(endpoint)


@router.delete("/{endpoint_id}", status_code=204)
def delete_endpoint(
    endpoint_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(WEBHOOKS_MANAGE)),
    db: Session = Depends(get_db),
) -> None:
    endpoint = _endpoint(db, principal.organization_id or "", endpoint_id)
    db.delete(endpoint)
    db.commit()
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="webhook.delete",
        resource_type="webhook_endpoint",
        resource_id=endpoint_id,
        request=request,
        commit=True,
    )


@router.post("/{endpoint_id}/test", response_model=WebhookTestOut)
def test_endpoint(
    endpoint_id: str,
    request: Request,
    principal: AuthPrincipal = Depends(require_org(WEBHOOKS_MANAGE)),
    db: Session = Depends(get_db),
) -> WebhookTestOut:
    endpoint = _endpoint(db, principal.organization_id or "", endpoint_id)
    _validate_url(endpoint.url)
    event = OutboxEvent(
        id=new_id(),
        organization_id=endpoint.organization_id,
        type="webhook.test",
        aggregate_type="webhook_endpoint",
        aggregate_id=endpoint.id,
        payload={"message": "teste de webhook", "endpoint_id": endpoint.id},
        processed_at=utcnow(),
    )
    db.add(event)
    delivery = WebhookDelivery(
        organization_id=endpoint.organization_id,
        endpoint_id=endpoint.id,
        outbox_event_id=event.id,
        event_type="webhook.test",
        payload={
            "type": "webhook.test",
            "id": event.id,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "data": event.payload,
        },
        status="pending",
        attempts=0,
        next_attempt_at=utcnow(),
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)
    deliver(db, delivery, endpoint=endpoint)
    log_audit(
        db,
        organization_id=principal.organization_id,
        actor_user_id=principal.user_id,
        action="webhook.test",
        resource_type="webhook_endpoint",
        resource_id=endpoint.id,
        metadata={"status": delivery.status, "response_status": delivery.response_status},
        request=request,
        commit=True,
    )
    return WebhookTestOut(delivery=WebhookDeliveryOut.model_validate(delivery))


@router.get("/{endpoint_id}/deliveries", response_model=list[WebhookDeliveryOut])
def list_deliveries(
    endpoint_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    principal: AuthPrincipal = Depends(require_org(WEBHOOKS_MANAGE)),
    db: Session = Depends(get_db),
) -> list[WebhookDeliveryOut]:
    _endpoint(db, principal.organization_id or "", endpoint_id)
    deliveries = (
        db.query(WebhookDelivery)
        .filter(
            WebhookDelivery.endpoint_id == endpoint_id,
            WebhookDelivery.organization_id == principal.organization_id,
        )
        .order_by(WebhookDelivery.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [WebhookDeliveryOut.model_validate(delivery) for delivery in deliveries]


@router.post("/{endpoint_id}/deliveries/{delivery_id}/retry", response_model=WebhookDeliveryOut)
def retry_delivery(
    endpoint_id: str,
    delivery_id: str,
    principal: AuthPrincipal = Depends(require_org(WEBHOOKS_MANAGE)),
    db: Session = Depends(get_db),
) -> WebhookDeliveryOut:
    _endpoint(db, principal.organization_id or "", endpoint_id)
    delivery = (
        db.query(WebhookDelivery)
        .filter(
            WebhookDelivery.id == delivery_id,
            WebhookDelivery.endpoint_id == endpoint_id,
            WebhookDelivery.organization_id == principal.organization_id,
        )
        .one_or_none()
    )
    if delivery is None:
        raise HTTPException(status_code=404, detail="entrega não encontrada")
    delivery.status = "pending"
    delivery.attempts = 0
    delivery.next_attempt_at = utcnow()
    delivery.response_status = None
    delivery.response_body = None
    db.commit()
    db.refresh(delivery)
    return WebhookDeliveryOut.model_validate(delivery)
