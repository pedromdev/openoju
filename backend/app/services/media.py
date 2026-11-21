from __future__ import annotations

from fastapi.responses import RedirectResponse, StreamingResponse

from ..config import Settings, get_settings
from ..storage import StorageError, get_storage


def remote_media_response(
    key: str,
    media_type: str,
    *,
    settings: Settings | None = None,
    headers: dict[str, str] | None = None,
):
    """Serve an object from object storage.

    Prefers a presigned URL (S3, Azure SAS). When the backend cannot presign
    (or the SAS call fails, e.g. missing RBAC), it streams through the API so
    playback still works in private/restricted setups.
    """
    settings = settings or get_settings()
    storage = get_storage(settings)
    if getattr(storage, "supports_presigned_get", False):
        try:
            url = storage.presign_get(key)
        except StorageError:
            url = ""
        if url:
            return RedirectResponse(url, status_code=302)

    body, length = storage.open_stream(key)

    def chunks():
        try:
            while True:
                chunk = body.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            body.close()

    response_headers = dict(headers or {})
    if length:
        response_headers["Content-Length"] = str(length)
    return StreamingResponse(chunks(), media_type=media_type, headers=response_headers)
