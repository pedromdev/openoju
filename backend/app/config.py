from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OJU_",
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = BASE_DIR / "data"
    media_root: Path = Path("/srv/openoju")
    watch_dir: Path | None = None
    watch_interval_s: int = 30
    watch_min_age_s: int = 30
    # Folder watching is a single-tenant convenience. It must be bound to an
    # explicit organization; otherwise the watcher stays disabled.
    watch_org_slug: str | None = None

    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    vaapi_device: str = "/dev/dri/renderD128"
    enable_vaapi: bool = True

    auto_analyze: bool = True
    sample_fps: float = 1.0
    analysis_width: int = 640
    warmup_frames: int = 5
    motion_threshold: float = 0.003
    min_area_ratio: float = 0.0005
    start_hits: int = 2
    end_gap: int = 3
    merge_gap: int = 5
    min_duration_s: float = 2.0
    max_duration_s: float = 300.0

    proxy_max_width: int = 1280
    proxy_crf: int = 26
    proxy_qp: int = 28

    job_timeout_s: int = 6 * 3600
    upload_chunk_size: int = 8 * 1024 * 1024
    upload_max_bytes: int = 60 * 1024 * 1024 * 1024
    upload_session_ttl_hours: int = 48
    cors_origins: str = "http://localhost:4200,http://127.0.0.1:4200"
    default_profile_name: str = "Default"

    detector_enabled: bool = False
    detector_model: str | None = None

    # Persistence
    database_url: str = ""

    # Sessions and security
    session_cookie: str = "openoju_session"
    csrf_cookie: str = "openoju_csrf"
    session_ttl_hours: int = 720
    cookie_secure: bool = True
    csrf_enabled: bool = True
    setup_token: str = ""
    secret_key: str = ""
    fernet_key: str = ""
    public_base_url: str = "http://localhost:8000"

    # Login rate limiting (in-process; document single-replica limitation)
    login_rate_limit_attempts: int = 10
    login_rate_limit_window_s: int = 300

    # Storage: "local" or "s3" (s3 lands in phase 5)
    storage_backend: str = "local"
    s3_endpoint: str = ""
    s3_internal_endpoint: str = ""
    s3_bucket: str = "openoju"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_part_size: int = 16 * 1024 * 1024
    s3_presign_expires_s: int = 86400

    # OIDC (phase 4). Kept here so setup status can advertise availability.
    oidc_enabled: bool = False
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_uri: str = ""
    oidc_scopes: str = "openid email profile"
    oidc_auto_provision: bool = False
    oidc_default_group: str = "Viewer"
    frontend_base_url: str = ""

    # Webhooks
    webhook_timeout_s: int = 10
    webhook_max_attempts: int = 6
    webhook_allow_http: bool = False
    dispatcher_interval_s: int = 10
    dispatcher_batch_size: int = 50

    # Maintenance / retention
    maintenance_interval_s: int = 3600
    retention_webhook_days: int = 30
    retention_session_days: int = 30

    # Retention
    retention_media_days: int = 30
    retention_access_log_months: int = 6
    retention_audit_months: int = 12

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def effective_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.db_path}"

    @property
    def is_sqlite(self) -> bool:
        return self.effective_database_url.startswith("sqlite")

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def effective_watch_dir(self) -> Path:
        return self.watch_dir or (self.media_root / "inbox")

    @property
    def uploads_dir(self) -> Path:
        return self.media_root / "uploads"

    @property
    def uploads_tmp_dir(self) -> Path:
        return self.uploads_dir / ".tmp"

    @property
    def proxy_dir(self) -> Path:
        return self.media_root / "proxy"

    @property
    def thumbs_dir(self) -> Path:
        return self.media_root / "thumbs"

    @property
    def clips_dir(self) -> Path:
        return self.media_root / "clips"

    def org_media_dir(self, organization_id: str) -> Path:
        return self.media_root / "org" / organization_id

    def org_uploads_dir(self, organization_id: str) -> Path:
        return self.org_media_dir(organization_id) / "videos"

    def org_proxy_dir(self, organization_id: str) -> Path:
        return self.org_media_dir(organization_id) / "proxy"

    def org_thumbs_dir(self, organization_id: str) -> Path:
        return self.org_media_dir(organization_id) / "thumbs"

    def org_clips_dir(self, organization_id: str) -> Path:
        return self.org_media_dir(organization_id) / "clips"

    def storage_key(self, organization_id: str, kind: str, name: str) -> str:
        return f"org/{organization_id}/{kind}/{name}"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.jobs_dir,
            self.media_root,
            self.uploads_dir,
            self.uploads_tmp_dir,
            self.proxy_dir,
            self.thumbs_dir,
            self.clips_dir,
            self.effective_watch_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def ensure_org_dirs(self, organization_id: str) -> None:
        for path in (
            self.org_uploads_dir(organization_id),
            self.org_proxy_dir(organization_id),
            self.org_thumbs_dir(organization_id),
            self.org_clips_dir(organization_id),
        ):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def oidc_callback_url(self) -> str:
        if self.oidc_redirect_uri:
            return self.oidc_redirect_uri
        return f"{self.public_base_url.rstrip('/')}/api/v1/auth/oidc/callback"

    @property
    def ui_base_url(self) -> str:
        return (self.frontend_base_url or self.public_base_url).rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
