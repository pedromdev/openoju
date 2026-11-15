from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import Settings


class FfmpegError(RuntimeError):
    pass


@dataclass
class VideoProbe:
    duration_s: float | None
    fps: float | None
    width: int | None
    height: int | None
    video_codec: str | None
    audio_codec: str | None
    recorded_at: str | None
    format_name: str | None
    has_audio: bool


def _parse_rate(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if "/" in value:
            num, den = value.split("/", 1)
            den_f = float(den)
            if den_f == 0:
                return None
            return float(num) / den_f
        return float(value)
    except (TypeError, ValueError):
        return None


def probe_video(path: str | Path, settings: Settings) -> VideoProbe:
    cmd = [
        settings.ffprobe_bin,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FfmpegError(f"ffprobe falhou: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or "").strip()[:800]
        raise FfmpegError(f"ffprobe não reconheceu o vídeo: {detail}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise FfmpegError("ffprobe retornou JSON inválido") from exc

    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise FfmpegError("o arquivo não contém stream de vídeo")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    tags = fmt.get("tags", {}) or {}
    vtags = video.get("tags", {}) or {}
    duration_raw = fmt.get("duration") or video.get("duration")
    try:
        duration = float(duration_raw) if duration_raw is not None else None
    except (TypeError, ValueError):
        duration = None
    if duration is not None and duration <= 0:
        duration = None

    recorded_at = tags.get("creation_time") or vtags.get("creation_time")
    if not recorded_at:
        # DHAV stores the wall clock as an absolute epoch in format.start_time.
        # It is already the camera's local wall clock (no timezone attached), so
        # keep it naive to avoid shifting the displayed time in the browser.
        try:
            start_epoch = float(fmt.get("start_time") or video.get("start_time") or 0)
        except (TypeError, ValueError):
            start_epoch = 0
        if start_epoch > 1_000_000_000:
            recorded_at = datetime.fromtimestamp(
                start_epoch, tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S")

    return VideoProbe(
        duration_s=duration,
        fps=_parse_rate(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        width=int(video["width"]) if video.get("width") else None,
        height=int(video["height"]) if video.get("height") else None,
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name") if audio else None,
        recorded_at=tags.get("creation_time") or vtags.get("creation_time") or recorded_at,
        format_name=fmt.get("format_name"),
        has_audio=audio is not None,
    )


def target_dimensions(
    width: int | None, height: int | None, max_width: int
) -> tuple[int, int] | None:
    if not width or not height:
        return None
    target_w = min(int(width), int(max_width))
    target_h = int(round(height * target_w / width))
    if target_h % 2:
        target_h += 1
    target_w -= target_w % 2
    return max(2, target_w), max(2, target_h)


def _base_output_args() -> list[str]:
    return [
        "-sn",
        "-dn",
        "-movflags",
        "+faststart",
    ]


def _copy_command(
    input_path: Path, output_path: Path, settings: Settings, probe: VideoProbe
) -> list[str]:
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "copy",
    ]
    if probe.has_audio:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]
    cmd += _base_output_args()
    cmd.append(str(output_path))
    return cmd


def _vaapi_command(
    input_path: Path,
    output_path: Path,
    settings: Settings,
    probe: VideoProbe,
    dims: tuple[int, int],
) -> list[str]:
    w, h = dims
    cmd = [
        settings.ffmpeg_bin,
        "-y",
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
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        f"scale_vaapi=w={w}:h={h}",
        "-c:v",
        "h264_vaapi",
        "-rc_mode",
        "CQP",
        "-qp",
        str(settings.proxy_qp),
    ]
    if probe.has_audio:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]
    cmd += _base_output_args()
    cmd.append(str(output_path))
    return cmd


def _x264_command(
    input_path: Path,
    output_path: Path,
    settings: Settings,
    probe: VideoProbe,
    dims: tuple[int, int],
) -> list[str]:
    w, h = dims
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        f"scale={w}:{h}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        str(settings.proxy_crf),
    ]
    if probe.has_audio:
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]
    cmd += _base_output_args()
    cmd.append(str(output_path))
    return cmd


def proxy_command_candidates(
    input_path: Path,
    output_path: Path,
    settings: Settings,
    probe: VideoProbe,
) -> list[tuple[str, list[str]]]:
    dims = target_dimensions(probe.width, probe.height, settings.proxy_max_width) or (
        1280,
        720,
    )
    codec = (probe.video_codec or "").lower()
    candidates: list[tuple[str, list[str]]] = []
    if codec in {"h264", "avc"}:
        candidates.append(("copy", _copy_command(input_path, output_path, settings, probe)))
    if codec in {"hevc", "h265"} and settings.enable_vaapi:
        if Path(settings.vaapi_device).exists():
            candidates.append(
                ("vaapi", _vaapi_command(input_path, output_path, settings, probe, dims))
            )
    candidates.append(("x264", _x264_command(input_path, output_path, settings, probe, dims)))
    # Deduplicate identical command lines while preserving order.
    seen: set[tuple[str, ...]] = set()
    unique: list[tuple[str, list[str]]] = []
    for mode, cmd in candidates:
        key = tuple(cmd)
        if key not in seen:
            seen.add(key)
            unique.append((mode, cmd))
    return unique


def run_ffmpeg(
    cmd: list[str], log_path: Path, timeout_s: int
) -> tuple[int, str]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(cmd) + "\n\n")
        log.flush()
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=log,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            log.write(f"\n[timeout após {timeout_s}s]\n")
            return 124, f"timeout após {timeout_s}s: {exc}"
        except OSError as exc:
            log.write(f"\n[erro ao executar ffmpeg: {exc}]\n")
            return 127, str(exc)
    return proc.returncode, ""


def ensure_proxy(
    input_path: Path,
    output_path: Path,
    settings: Settings,
    probe: VideoProbe,
    log_path: Path,
) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 0:
        return "existing"
    errors: list[str] = []
    for mode, cmd in proxy_command_candidates(input_path, output_path, settings, probe):
        rc, err = run_ffmpeg(cmd, log_path, settings.job_timeout_s)
        if rc == 0 and output_path.exists() and output_path.stat().st_size > 0:
            return mode
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        errors.append(f"{mode}: rc={rc} {err}".strip())
    raise FfmpegError("não foi possível gerar o proxy MP4: " + " | ".join(errors))


def analysis_input(video_source: str, proxy_path: str | None) -> Path:
    if proxy_path:
        proxy = Path(proxy_path)
        if proxy.exists() and proxy.stat().st_size > 0:
            return proxy
    return Path(video_source)


def cut_clip(
    input_path: Path,
    output_path: Path,
    start_s: float,
    end_s: float,
    settings: Settings,
    log_path: Path,
) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    start = max(0.0, start_s - 2.0)
    duration = max(1.0, (end_s - start_s) + 4.0)
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    rc, _ = run_ffmpeg(cmd, log_path, 600)
    if rc == 0 and output_path.exists() and output_path.stat().st_size > 0:
        return True
    if output_path.exists():
        output_path.unlink(missing_ok=True)
    # Fallback: precise re-encode for streams whose keyframes make copy unusable.
    cmd_fallback = [
        settings.ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(input_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "24",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    rc, _ = run_ffmpeg(cmd_fallback, log_path, 600)
    return rc == 0 and output_path.exists() and output_path.stat().st_size > 0


def extract_thumbnail(
    input_path: Path,
    output_path: Path,
    at_s: float,
    settings: Settings,
    log_path: Path,
) -> bool:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        settings.ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, at_s):.3f}",
        "-i",
        str(input_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=480:-2",
        "-q:v",
        "3",
        str(output_path),
    ]
    rc, _ = run_ffmpeg(cmd, log_path, 120)
    return rc == 0 and output_path.exists() and output_path.stat().st_size > 0


def disk_usage(path: Path) -> tuple[int, int]:
    usage = shutil.disk_usage(path)
    return usage.free, usage.total
