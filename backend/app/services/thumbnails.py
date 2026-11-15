from __future__ import annotations

from pathlib import Path

from ..config import Settings
from ..models import Event, Video
from .ffmpeg import analysis_input, extract_thumbnail


def thumbnail_timestamp(
    start_s: float, end_s: float, duration_s: float | None = None
) -> float:
    """Return the midpoint of an event, clamped to the video duration."""
    start = max(0.0, float(start_s))
    end = max(start, float(end_s))
    midpoint = start + (end - start) / 2.0
    if duration_s is not None and duration_s > 0:
        midpoint = min(midpoint, max(0.0, float(duration_s) - 0.1))
    return max(0.0, midpoint)


def refresh_event_thumbnail(
    video: Video,
    event: Event,
    settings: Settings,
) -> bool:
    """Regenerate one event thumbnail from the midpoint of its interval."""
    source = analysis_input(video.source_path, video.proxy_path)
    if not source.exists():
        return False

    if event.thumbnail_path:
        target = Path(event.thumbnail_path)
    else:
        target = settings.org_thumbs_dir(video.organization_id) / f"{event.id}.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f"{target.stem}.tmp{target.suffix}")
    log_dir = settings.data_dir / "thumb-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{event.id}.log"

    at_s = thumbnail_timestamp(event.start_s, event.end_s, video.duration_s)
    if extract_thumbnail(source, temp, at_s, settings, log_path):
        temp.replace(target)
        event.thumbnail_path = str(target)
        return True
    temp.unlink(missing_ok=True)
    return False
