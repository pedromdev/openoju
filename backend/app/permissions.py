from __future__ import annotations

from typing import Final

ORGANIZATION_VIEW: Final = "organization.view"
ORGANIZATION_MANAGE: Final = "organization.manage"
MEMBERS_VIEW: Final = "members.view"
MEMBERS_INVITE: Final = "members.invite"
MEMBERS_MANAGE: Final = "members.manage"
GROUPS_MANAGE: Final = "groups.manage"
VIDEOS_VIEW: Final = "videos.view"
VIDEOS_UPLOAD: Final = "videos.upload"
VIDEOS_MANAGE: Final = "videos.manage"
VIDEOS_ANALYZE: Final = "videos.analyze"
EVENTS_VIEW: Final = "events.view"
EVENTS_REVIEW: Final = "events.review"
PROFILES_VIEW: Final = "profiles.view"
PROFILES_MANAGE: Final = "profiles.manage"
JOBS_VIEW: Final = "jobs.view"
JOBS_CANCEL: Final = "jobs.cancel"
API_KEYS_MANAGE: Final = "api_keys.manage"
WEBHOOKS_MANAGE: Final = "webhooks.manage"
AUDIT_VIEW: Final = "audit.view"
PRIVACY_MANAGE: Final = "privacy.manage"
DSR_MANAGE: Final = "data_subject_requests.manage"

PERMISSIONS: Final[tuple[str, ...]] = (
    ORGANIZATION_VIEW,
    ORGANIZATION_MANAGE,
    MEMBERS_VIEW,
    MEMBERS_INVITE,
    MEMBERS_MANAGE,
    GROUPS_MANAGE,
    VIDEOS_VIEW,
    VIDEOS_UPLOAD,
    VIDEOS_MANAGE,
    VIDEOS_ANALYZE,
    EVENTS_VIEW,
    EVENTS_REVIEW,
    PROFILES_VIEW,
    PROFILES_MANAGE,
    JOBS_VIEW,
    JOBS_CANCEL,
    API_KEYS_MANAGE,
    WEBHOOKS_MANAGE,
    AUDIT_VIEW,
    PRIVACY_MANAGE,
    DSR_MANAGE,
)

_VIEWER = (
    ORGANIZATION_VIEW,
    VIDEOS_VIEW,
    EVENTS_VIEW,
    PROFILES_VIEW,
    JOBS_VIEW,
)

_OPERATOR = _VIEWER + (
    VIDEOS_UPLOAD,
    VIDEOS_ANALYZE,
    VIDEOS_MANAGE,
    EVENTS_REVIEW,
    PROFILES_MANAGE,
    JOBS_CANCEL,
)

_ADMIN = PERMISSIONS

ROLE_TEMPLATES: Final[dict[str, dict[str, object]]] = {
    "Owner": {
        "description": "Controle total da organização. Grupo imutável.",
        "permissions": list(PERMISSIONS),
        "is_system": True,
    },
    "Admin": {
        "description": "Administração completa, exceto remover o último owner.",
        "permissions": list(_ADMIN),
        "is_system": True,
    },
    "Operator": {
        "description": "Upload, análise, revisão, exclusão e gestão de perfis.",
        "permissions": list(_OPERATOR),
        "is_system": True,
    },
    "Viewer": {
        "description": "Somente leitura de vídeos, eventos, perfis e jobs.",
        "permissions": list(_VIEWER),
        "is_system": True,
    },
}

DEFAULT_ROLE = "Viewer"

# Scopes accepted by API keys. Machine routes only use these.
API_KEY_SCOPES: Final[tuple[str, ...]] = (
    "ingest:write",
    "videos:read",
    "events:read",
    "profiles:read",
)

# A permission is denied unless explicitly present. This helper exists so
# unknown permissions fail closed during development.
def is_known_permission(value: str) -> bool:
    return value in PERMISSIONS
