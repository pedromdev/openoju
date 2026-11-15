from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .api import (
    auth,
    compliance,
    events,
    ingest,
    jobs,
    organizations,
    profiles,
    uploads,
    videos,
    webhooks,
)
from .auth import csrf_is_valid
from .config import BASE_DIR, get_settings
from .db import SessionLocal, init_db
from .schemas import HealthOut
from .services.ffmpeg import disk_usage
from .services.uploads import cleanup_stale_sessions

logger = logging.getLogger("openoju")

CSRF_EXEMPT_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/setup",
    "/api/v1/auth/invitations/accept",
    "/api/v1/auth/oidc/callback",
}
CSRF_EXEMPT_PREFIXES = ("/api/v1/privacy/",)
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    settings.ensure_dirs()
    if settings.is_sqlite:
        init_db()
    db = SessionLocal()
    try:
        cleanup_stale_sessions(db, settings)
    except Exception as exc:  # noqa: BLE001 - startup must not crash on cleanup
        logger.warning("limpeza de uploads ignorada: %s", exc)
        db.rollback()
    finally:
        db.close()
    yield


settings = get_settings()
app = FastAPI(
    title="OpenOju",
    version="0.2.0",
    description="Análise assíncrona de movimentação em vídeos de câmera de segurança.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    if (
        settings.csrf_enabled
        and request.method in UNSAFE_METHODS
        and request.url.path.startswith("/api/")
        and request.url.path not in CSRF_EXEMPT_PATHS
        and not any(
            request.url.path.startswith(prefix) for prefix in CSRF_EXEMPT_PREFIXES
        )
        and settings.session_cookie in request.cookies
        and not request.headers.get("authorization", "").lower().startswith("bearer ")
    ):
        if not csrf_is_valid(request):
            return JSONResponse(
                status_code=403, content={"detail": "CSRF token inválido"}
            )
    return await call_next(request)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    if settings.cookie_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


app.include_router(auth.router, prefix="/api/v1")
app.include_router(organizations.router, prefix="/api/v1")
app.include_router(videos.router, prefix="/api/v1")
app.include_router(uploads.router, prefix="/api/v1")
app.include_router(ingest.router, prefix="/api/v1")
app.include_router(events.router, prefix="/api/v1")
app.include_router(profiles.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")
app.include_router(compliance.router, prefix="/api/v1")


@app.get("/api/health", response_model=HealthOut, tags=["health"])
@app.get("/api/v1/health", response_model=HealthOut, tags=["health"])
def health() -> HealthOut:
    try:
        settings.media_root.mkdir(parents=True, exist_ok=True)
        free, total = disk_usage(settings.media_root)
        status = "ok"
    except OSError as exc:
        # A read-only or missing scratch volume must not turn into a restart
        # loop; report it so the orchestrator can surface a degraded probe.
        logger.warning("media root indisponível: %s", exc)
        free, total = 0, 0
        status = "degraded"
    return HealthOut(
        status=status,
        media_root=str(settings.media_root),
        data_dir=str(settings.data_dir),
        media_free_bytes=free,
        media_total_bytes=total,
    )


@app.get("/api", tags=["health"])
def api_root() -> dict[str, str]:
    return {
        "name": "openoju",
        "version": "0.2.0",
        "docs": "/docs",
    }


def _frontend_dist() -> Path | None:
    root = BASE_DIR / "frontend" / "dist"
    if not root.exists():
        return None
    preferred = root / "openoju" / "browser"
    if preferred.exists():
        return preferred
    candidates = sorted(root.glob("*/browser"))
    return candidates[0] if candidates else None


dist = _frontend_dist()
if dist is not None:
    dist_root = dist.resolve()

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/") or full_path in {"docs", "openapi.json", "redoc"}:
            raise HTTPException(status_code=404, detail="rota não encontrada")
        candidate = (dist_root / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(dist_root):
            return FileResponse(candidate)
        return FileResponse(dist_root / "index.html")

else:

    @app.get("/", tags=["health"])
    def root() -> dict[str, str]:
        return {
            "name": "openoju",
            "frontend": "dev server em http://localhost:4200",
            "docs": "/docs",
        }
