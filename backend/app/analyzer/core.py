from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..config import Settings
from ..services.ffmpeg import FfmpegError, VideoProbe, probe_video, target_dimensions
from .motion import FrameSignal, MotionParams, aggregate_events

ProgressCallback = Callable[[dict], None]


@dataclass
class AnalysisParams:
    sample_fps: float = 1.0
    width: int = 640
    masks: list[dict] | None = None
    roi: dict | None = None
    motion: MotionParams = field(default_factory=MotionParams)
    decoder: str = "auto"
    recorded_at: str | None = None


def _mask_rect(mask: dict) -> tuple[float, float, float, float] | None:
    try:
        if {"x", "y", "w", "h"} <= set(mask):
            x = float(mask["x"])
            y = float(mask["y"])
            w = float(mask["w"])
            h = float(mask["h"])
        elif {"x1", "y1", "x2", "y2"} <= set(mask):
            x = float(mask["x1"])
            y = float(mask["y1"])
            w = float(mask["x2"]) - x
            h = float(mask["y2"]) - y
        else:
            return None
    except (TypeError, ValueError):
        return None
    return x, y, w, h


def apply_masks(frame: np.ndarray, masks: list[dict] | None) -> np.ndarray:
    if not masks:
        return frame
    height, width = frame.shape[:2]
    for mask in masks:
        rect = _mask_rect(mask)
        if rect is None:
            continue
        x, y, w, h = rect
        x1 = max(0, min(width, int(round(x * width))))
        y1 = max(0, min(height, int(round(y * height))))
        x2 = max(0, min(width, int(round((x + w) * width))))
        y2 = max(0, min(height, int(round((y + h) * height))))
        if x2 > x1 and y2 > y1:
            frame[y1:y2, x1:x2] = 0
    return frame


def _use_vaapi(decoder: str, probe: VideoProbe, settings: Settings) -> bool:
    if decoder == "vaapi":
        return True
    if decoder == "cpu":
        return False
    codec = (probe.video_codec or "").lower()
    return (
        settings.enable_vaapi
        and codec in {"h264", "avc", "hevc", "h265"}
        and Path(settings.vaapi_device).exists()
    )


def build_decode_command(
    input_path: Path,
    probe: VideoProbe,
    params: AnalysisParams,
    settings: Settings,
) -> tuple[list[str], int, int, str]:
    dims = target_dimensions(probe.width, probe.height, params.width) or (640, 360)
    width, height = dims
    fps = max(0.05, float(params.sample_fps))
    if _use_vaapi(params.decoder, probe, settings):
        filters = (
            f"fps={fps},scale_vaapi=w={width}:h={height},"
            "hwdownload,format=nv12,format=gray"
        )
        cmd = [
            settings.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-hwaccel",
            "vaapi",
            "-hwaccel_device",
            settings.vaapi_device,
            "-hwaccel_output_format",
            "vaapi",
            "-i",
            str(input_path),
            "-vf",
            filters,
            "-f",
            "rawvideo",
            "-",
        ]
        return cmd, width, height, "vaapi"
    filters = f"fps={fps},scale={width}:{height},format=gray"
    cmd = [
        settings.ffmpeg_bin,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vf",
        filters,
        "-f",
        "rawvideo",
        "-",
    ]
    return cmd, width, height, "cpu"


def _read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _parse_recorded_at(recorded_at: str | None) -> datetime | None:
    if not recorded_at:
        return None
    value = recorded_at.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Keep naive camera wall-clock values naive; only normalize explicit offsets.
    return parsed


def _wallclock(recorded_at: str | None, seconds: float) -> str | None:
    base = _parse_recorded_at(recorded_at)
    if base is None:
        return None
    return (base + timedelta(seconds=seconds)).isoformat()


def analyze_video(
    input_path: Path,
    output_dir: Path,
    params: AnalysisParams,
    settings: Settings,
    progress_cb: ProgressCallback | None = None,
) -> dict:
    probe = probe_video(input_path, settings)
    if params.recorded_at:
        probe.recorded_at = params.recorded_at
    cmd, width, height, decoder = build_decode_command(
        input_path, probe, params, settings
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "analyze-ffmpeg.log"
    total_frames = (
        int(round(probe.duration_s * params.sample_fps))
        if probe.duration_s
        else None
    )
    subtractor = cv2.createBackgroundSubtractorMOG2(
        history=params.motion.mog_history,
        varThreshold=params.motion.var_threshold,
        detectShadows=params.motion.detect_shadows,
    )
    kernel = np.ones((3, 3), np.uint8)
    frame_size = width * height
    signals = []
    frame_index = 0
    previous_frame: np.ndarray | None = None
    previous_mean: float | None = None
    progress_step = max(1, (total_frames or 100) // 100)

    def emit(stage: str, value: float | None, message: str | None = None, t: float | None = None) -> None:
        if progress_cb is None:
            return
        progress_cb(
            {
                "stage": stage,
                "progress": value,
                "message": message,
                "video_time_s": round(t, 3) if t is not None else None,
            }
        )

    emit("analyze", 0.0, "iniciando decodificação")
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(cmd) + "\n\n")
        log.flush()
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=log,
                bufsize=0,
            )
        except OSError as exc:
            raise FfmpegError(f"não foi possível iniciar o ffmpeg: {exc}") from exc

        assert process.stdout is not None
        try:
            while True:
                buffer = _read_exact(process.stdout, frame_size)
                if len(buffer) < frame_size:
                    break
                frame = (
                    np.frombuffer(buffer, dtype=np.uint8)
                    .reshape(height, width)
                    .copy()
                )
                apply_masks(frame, params.masks)
                mean = float(frame.mean())
                mean_delta = (
                    abs(mean - previous_mean) if previous_mean is not None else 0.0
                )
                diff_bin = np.zeros((height, width), dtype=np.uint8)
                diff_ratio = 0.0
                if params.motion.use_frame_diff and previous_frame is not None:
                    diff_raw = cv2.absdiff(frame, previous_frame)
                    _, diff_bin = cv2.threshold(
                        diff_raw,
                        params.motion.diff_threshold,
                        255,
                        cv2.THRESH_BINARY,
                    )
                    diff_ratio = cv2.countNonZero(diff_bin) / float(frame_size)

                if (
                    previous_frame is not None
                    and mean_delta >= params.motion.illumination_mean_delta
                    and diff_ratio >= params.motion.illumination_diff_ratio
                ):
                    # Global brightness jump (IR/day-night switch, sunrise, lights).
                    # Reset the background model and do not create a motion sample.
                    subtractor = cv2.createBackgroundSubtractorMOG2(
                        history=params.motion.mog_history,
                        varThreshold=params.motion.var_threshold,
                        detectShadows=params.motion.detect_shadows,
                    )
                    previous_frame = frame
                    previous_mean = mean
                    frame_index += 1
                    continue

                fg_mog = subtractor.apply(frame)
                fg = (
                    np.where(fg_mog >= 200, 255, 0).astype(np.uint8)
                    if fg_mog is not None
                    else np.zeros((height, width), dtype=np.uint8)
                )
                if params.motion.use_frame_diff and previous_frame is not None:
                    fg = cv2.bitwise_or(fg, diff_bin)
                previous_frame = frame
                previous_mean = mean
                fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, kernel)
                fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel)
                count = int(cv2.countNonZero(fg))
                score = count / float(frame_size)
                area_ratio = 0.0
                bbox: list[int] | None = None
                contours, _ = cv2.findContours(
                    fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                )
                if contours:
                    largest = max(contours, key=cv2.contourArea)
                    area = float(cv2.contourArea(largest))
                    area_ratio = area / float(frame_size)
                    x, y, w, h = cv2.boundingRect(largest)
                    bbox = [int(x), int(y), int(w), int(h)]
                t = frame_index / params.sample_fps
                if frame_index >= params.motion.warmup_frames:
                    signals.append(
                        FrameSignal(
                            t=t,
                            score=score,
                            area_ratio=area_ratio,
                            bbox=bbox,
                        )
                    )
                frame_index += 1
                if total_frames and (
                    frame_index % progress_step == 0 or frame_index == total_frames
                ):
                    emit(
                        "analyze",
                        min(1.0, frame_index / total_frames),
                        f"{frame_index}/{total_frames} frames",
                        t,
                    )
        finally:
            assert process.stdout is not None
            process.stdout.close()
            returncode = process.wait()

    if returncode != 0:
        tail = ""
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        except OSError:
            pass
        raise FfmpegError(f"ffmpeg falhou com código {returncode}: {tail}")

    events = aggregate_events(signals, params.motion, 1.0 / params.sample_fps)
    event_dicts = []
    for event in events:
        payload = event.to_dict()
        payload["start_wallclock"] = _wallclock(probe.recorded_at, event.start_s)
        payload["end_wallclock"] = _wallclock(probe.recorded_at, event.end_s)
        payload["label"] = "movement"
        event_dicts.append(payload)

    result = {
        "schema_version": 1,
        "video": {
            "path": str(input_path),
            "duration_s": probe.duration_s,
            "fps": probe.fps,
            "width": probe.width,
            "height": probe.height,
            "video_codec": probe.video_codec,
            "audio_codec": probe.audio_codec,
            "recorded_at": probe.recorded_at,
        },
        "analysis": {
            "sample_fps": params.sample_fps,
            "frame_width": width,
            "frame_height": height,
            "decoder": decoder,
            "masks": params.masks or [],
            "roi": params.roi,
            "motion": params.motion.__dict__,
            "analyzed_frames": frame_index,
        },
        "summary": {
            "event_count": len(event_dicts),
            "motion_seconds": round(sum(e["duration_s"] for e in event_dicts), 3),
        },
        "events": event_dicts,
    }
    result_path = output_dir / "result.json"
    temp_path = output_dir / "result.json.tmp"
    temp_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temp_path.replace(result_path)
    emit("completed", 1.0, f"{len(event_dicts)} evento(s)")
    return result
