from __future__ import annotations

import subprocess
from pathlib import Path

import cv2
import numpy as np

from app.config import get_settings
from app.models import Event, Video
from app.services.ffmpeg import extract_thumbnail
from app.services.thumbnails import (
    refresh_event_thumbnail,
    thumbnail_timestamp,
)


def _two_scene_video(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=5:d=5",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:s=320x180:r=5:d=5",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        timeout=60,
    )


def _is_red(path: Path) -> bool:
    image = cv2.imread(str(path))
    assert image is not None
    mean = image.reshape(-1, 3).mean(axis=0)
    blue, green, red = mean
    return red > blue and red > green


def test_thumbnail_timestamp_midpoint() -> None:
    assert thumbnail_timestamp(10, 20) == 15
    assert thumbnail_timestamp(0, 0) == 0
    assert thumbnail_timestamp(1590, 1651) == 1620.5
    assert thumbnail_timestamp(10, 20, duration_s=12) == 11.9


def test_extract_thumbnail_seeks_to_requested_scene(tmp_path: Path) -> None:
    video = tmp_path / "two-scenes.mp4"
    thumb = tmp_path / "frame.jpg"
    _two_scene_video(video)
    settings = get_settings()
    assert extract_thumbnail(
        video, thumb, 5.0, settings, tmp_path / "thumb.log"
    )
    assert _is_red(thumb)


def test_refresh_event_thumbnail_uses_event_midpoint(tmp_path: Path) -> None:
    video_path = tmp_path / "two-scenes.mp4"
    thumb = tmp_path / "event.jpg"
    _two_scene_video(video_path)
    video = Video(
        id="video-test",
        filename="two-scenes.mp4",
        source_path=str(video_path),
        proxy_path=None,
        duration_s=10.0,
    )
    event = Event(
        id="event-test",
        video_id=video.id,
        start_s=4.0,
        end_s=8.0,
        thumbnail_path=str(thumb),
    )
    settings = get_settings()
    assert refresh_event_thumbnail(video, event, settings)
    assert thumb.exists()
    assert _is_red(thumb)
