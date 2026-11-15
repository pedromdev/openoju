from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from ..config import get_settings
from .core import AnalysisParams, analyze_video
from .motion import MotionParams


def _load_profile(path: Path | None) -> dict:
    if path is None:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openoju-analyzer",
        description="Analisa um vídeo e produz eventos de movimento.",
    )
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--profile", type=Path, default=None)
    parser.add_argument("--sample-fps", type=float, default=None)
    parser.add_argument("--width", type=int, default=None)
    parser.add_argument("--recorded-at", type=str, default=None)
    parser.add_argument("--decoder", choices=["auto", "cpu", "vaapi"], default="auto")
    parser.add_argument(
        "--progress-ndjson",
        action="store_true",
        help="Emite progresso como uma linha JSON por evento no stdout.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    settings.ensure_dirs()
    profile = _load_profile(args.profile)

    defaults = MotionParams(
        threshold=settings.motion_threshold,
        min_area_ratio=settings.min_area_ratio,
        warmup_frames=settings.warmup_frames,
        start_hits=settings.start_hits,
        end_gap=settings.end_gap,
        merge_gap_s=float(settings.merge_gap),
        min_duration_s=settings.min_duration_s,
        max_duration_s=settings.max_duration_s,
    )
    motion_data = profile.get("motion")
    if motion_data is None:
        profile_settings = profile.get("settings") or {}
        if isinstance(profile_settings, dict):
            motion_data = profile_settings.get("motion")
    motion = MotionParams.from_dict(motion_data if isinstance(motion_data, dict) else None, defaults)

    params = AnalysisParams(
        sample_fps=args.sample_fps or settings.sample_fps,
        width=args.width or settings.analysis_width,
        masks=profile.get("masks") or [],
        roi=profile.get("roi"),
        motion=motion,
        decoder=args.decoder,
        recorded_at=args.recorded_at,
    )

    def progress(payload: dict) -> None:
        if args.progress_ndjson:
            print(json.dumps(payload, ensure_ascii=False), flush=True)

    try:
        result = analyze_video(
            args.input.expanduser().resolve(),
            args.output.expanduser().resolve(),
            params,
            settings,
            progress_cb=progress,
        )
    except Exception as exc:  # noqa: BLE001 - CLI boundary must report any failure
        if params.decoder in {"auto", "vaapi"}:
            print(
                f"decoder {params.decoder} falhou ({exc}); tentando CPU",
                file=sys.stderr,
                flush=True,
            )
            params.decoder = "cpu"
            try:
                result = analyze_video(
                    args.input.expanduser().resolve(),
                    args.output.expanduser().resolve(),
                    params,
                    settings,
                    progress_cb=progress,
                )
            except Exception as retry_exc:  # noqa: BLE001
                print(
                    f"erro na análise (fallback CPU): {retry_exc}",
                    file=sys.stderr,
                    flush=True,
                )
                traceback.print_exc(file=sys.stderr)
                return 2
        else:
            print(f"erro na análise: {exc}", file=sys.stderr, flush=True)
            traceback.print_exc(file=sys.stderr)
            return 2

    if args.progress_ndjson:
        print(
            json.dumps(
                {
                    "stage": "result",
                    "progress": 1.0,
                    "events": result["summary"]["event_count"],
                    "result_path": str(args.output.resolve() / "result.json"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
