from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    masks: list[dict[str, Any]] = Field(default_factory=list)
    roi: dict[str, Any] | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class ProfileOut(ORMModel):
    id: str
    name: str
    masks: list[dict[str, Any]]
    roi: dict[str, Any] | None
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class VideoOut(ORMModel):
    id: str
    filename: str
    source_path: str | None
    storage_backend: str = "local"
    proxy_path: str | None
    thumbnail_path: str | None
    size_bytes: int
    duration_s: float | None
    fps: float | None
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None
    recorded_at: str | None
    status: str
    error: str | None
    profile_id: str | None
    created_at: datetime
    event_count: int = 0
    job_id: str | None = None
    job_status: str | None = None
    job_progress: float | None = None
    job_stage: str | None = None


class JobOut(ORMModel):
    id: str
    video_id: str
    status: str
    stage: str
    progress: float
    message: str | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class EventOut(ORMModel):
    id: str
    video_id: str
    start_s: float
    end_s: float
    start_wallclock: str | None
    end_wallclock: str | None
    score: float
    peak_score: float
    bbox: list[int] | None
    label: str
    thumbnail_path: str | None
    clip_path: str | None
    review_status: str
    notes: str | None
    created_at: datetime


class ReviewUpdate(BaseModel):
    review_status: Literal["new", "confirmed", "dismissed"]
    notes: str | None = None


class ImportRequest(BaseModel):
    path: str
    profile_id: str | None = None
    recursive: bool = True


class ScanRequest(BaseModel):
    path: str | None = None
    profile_id: str | None = None
    recursive: bool = True


class UploadResponse(BaseModel):
    video: VideoOut
    job: JobOut | None = None


class UploadInitRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    size: int = Field(gt=0)
    profile_id: str | None = None
    sha256: str | None = None


class UploadInitOut(BaseModel):
    upload_id: str
    filename: str
    part_size: int
    total_parts: int
    received_parts: list[int] = Field(default_factory=list)
    storage_backend: str = "local"
    part_urls: list[str] = Field(default_factory=list)


class UploadPartOut(BaseModel):
    upload_id: str
    received: int
    total_parts: int
    complete: bool
    etag: str | None = None


class UploadSessionOut(UploadInitOut):
    status: str
    error: str | None
    created_at: datetime

class HealthOut(BaseModel):
    status: str
    media_root: str
    data_dir: str
    media_free_bytes: int
    media_total_bytes: int


# ---------------------------------------------------------------------------
# Auth and organizations
# ---------------------------------------------------------------------------


class SetupStatusOut(BaseModel):
    setup_required: bool
    oidc_enabled: bool = False


class SetupRequest(BaseModel):
    token: str = Field(min_length=1)
    organization_name: str = Field(min_length=2, max_length=200)
    organization_slug: str | None = Field(default=None, max_length=80)
    owner_email: EmailStr
    owner_password: str = Field(min_length=12, max_length=200)
    owner_display_name: str = Field(default="", max_length=200)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class OrganizationOut(ORMModel):
    id: str
    name: str
    slug: str
    status: str


class GroupOut(ORMModel):
    id: str
    name: str
    description: str
    permissions: list[str]
    is_system: bool


class UserOut(ORMModel):
    id: str
    email: str
    display_name: str
    is_platform_admin: bool


class MeOut(BaseModel):
    user: UserOut
    organization: OrganizationOut | None = None
    permissions: list[str] = Field(default_factory=list)
    groups: list[GroupOut] = Field(default_factory=list)


class SwitchOrganizationRequest(BaseModel):
    slug: str


class InvitationInfoOut(BaseModel):
    organization_name: str
    organization_slug: str
    email: str
    expires_at: datetime
    groups: list[str] = Field(default_factory=list)
    requires_password: bool = True


class InvitationAcceptRequest(BaseModel):
    token: str = Field(min_length=10)
    password: str | None = Field(default=None, min_length=12, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)


class CsrfOut(BaseModel):
    csrf_token: str


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------


class MemberOut(BaseModel):
    id: str
    user_id: str
    email: str
    display_name: str
    status: str
    groups: list[GroupOut] = Field(default_factory=list)
    created_at: datetime


class InviteRequest(BaseModel):
    email: EmailStr
    group_ids: list[str] = Field(default_factory=list)


class InviteOut(BaseModel):
    membership_id: str
    invitation_id: str
    token: str
    expires_at: datetime


class MemberUpdate(BaseModel):
    status: Literal["active", "suspended"]
    group_ids: list[str] | None = None


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    permissions: list[str] = Field(default_factory=list)


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class ApiKeyOut(ORMModel):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None
    expires_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreatedOut(BaseModel):
    api_key: ApiKeyOut
    key: str


class AuditLogOut(ORMModel):
    id: str
    actor_user_id: str | None
    actor_api_key_id: str | None
    action: str
    resource_type: str | None
    resource_id: str | None
    metadata_json: dict[str, Any]
    ip: str | None
    user_agent: str | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Ingest (machine API)
# ---------------------------------------------------------------------------


class BatchCreate(BaseModel):
    name: str = Field(default="", max_length=200)


class BatchOut(ORMModel):
    id: str
    name: str
    status: str
    created_at: datetime


class IngestUploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    size: int = Field(gt=0)
    profile_id: str | None = None
    batch_id: str | None = None


class IngestUploadOut(BaseModel):
    upload_id: str
    part_size: int
    total_parts: int
    received_parts: list[int] = Field(default_factory=list)
    upload_url_template: str
    storage_backend: str = "local"
    part_urls: list[str] = Field(default_factory=list)


class CompletedPart(BaseModel):
    part_number: int = Field(ge=1)
    etag: str | None = None


class IngestCompleteRequest(BaseModel):
    parts: list[CompletedPart] | None = None


class IngestCompleteOut(BaseModel):
    video: VideoOut
    job: JobOut | None = None


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


class WebhookEndpointIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    url: str = Field(min_length=8, max_length=1000)
    events: list[str] = Field(default_factory=list)
    active: bool = True


class WebhookEndpointOut(ORMModel):
    id: str
    name: str
    url: str
    events: list[str]
    active: bool
    last_success_at: datetime | None
    failure_count: int
    created_at: datetime
    updated_at: datetime


class WebhookEndpointCreatedOut(BaseModel):
    endpoint: WebhookEndpointOut
    secret: str


class WebhookDeliveryOut(ORMModel):
    id: str
    endpoint_id: str
    event_type: str
    payload: dict[str, Any]
    status: str
    attempts: int
    next_attempt_at: datetime | None
    response_status: int | None
    response_body: str | None
    duration_ms: int | None
    delivered_at: datetime | None
    created_at: datetime


class WebhookTestOut(BaseModel):
    delivery: WebhookDeliveryOut


# ---------------------------------------------------------------------------
# Compliance
# ---------------------------------------------------------------------------


class PrivacySettingsIn(BaseModel):
    legal_basis: str = Field(default="legitimate_interest", max_length=120)
    retention_media_days: int = Field(default=30, ge=1, le=3650)
    retention_event_months: int = Field(default=12, ge=1, le=120)
    retention_access_logs_months: int = Field(default=6, ge=6, le=120)
    retention_audit_months: int = Field(default=12, ge=12, le=120)
    dpo_name: str | None = Field(default=None, max_length=200)
    dpo_email: EmailStr | None = None
    privacy_policy_version: str | None = Field(default=None, max_length=40)
    privacy_policy_url: str | None = Field(default=None, max_length=1000)
    camera_notice_text: str | None = None


class PrivacySettingsOut(ORMModel):
    organization_id: str
    legal_basis: str
    retention_media_days: int
    retention_event_months: int
    retention_access_logs_months: int
    retention_audit_months: int
    dpo_name: str | None
    dpo_email: str | None
    privacy_policy_version: str | None
    privacy_policy_url: str | None
    camera_notice_text: str | None
    updated_at: datetime


class PublicPrivacyOut(BaseModel):
    organization_name: str
    organization_slug: str
    legal_basis: str
    retention_media_days: int
    dpo_name: str | None
    dpo_email: str | None
    privacy_policy_version: str | None
    privacy_policy_url: str | None
    camera_notice_text: str | None


class DsrCreate(BaseModel):
    type: Literal["access", "correction", "deletion", "portability", "information"]
    requester_name: str = Field(min_length=2, max_length=200)
    requester_email: EmailStr
    description: str = Field(default="", max_length=4000)
    date_range_start: datetime | None = None
    date_range_end: datetime | None = None
    camera_profile_id: str | None = None


class DsrOut(ORMModel):
    id: str
    organization_id: str
    protocol: str
    type: str
    status: str
    requester_name: str
    requester_email: str
    description: str
    date_range_start: datetime | None
    date_range_end: datetime | None
    camera_profile_id: str | None
    assigned_user_id: str | None
    due_at: datetime | None
    resolution: str | None
    created_at: datetime
    updated_at: datetime


class DsrUpdate(BaseModel):
    status: Literal["new", "verified", "in_progress", "completed", "rejected"]
    assigned_user_id: str | None = None
    resolution: str | None = Field(default=None, max_length=4000)


class LegalHoldIn(BaseModel):
    resource_type: Literal["video", "event"]
    resource_id: str
    reason: str = Field(min_length=3, max_length=2000)
    expires_at: datetime | None = None


class LegalHoldOut(ORMModel):
    id: str
    organization_id: str
    resource_type: str
    resource_id: str
    reason: str
    created_by_user_id: str | None
    expires_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


class BulkDeleteRequest(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=100)


class BulkDeleteFailure(BaseModel):
    id: str
    status: int
    detail: str


class BulkDeleteResult(BaseModel):
    deleted: list[str] = Field(default_factory=list)
    failed: list[BulkDeleteFailure] = Field(default_factory=list)
