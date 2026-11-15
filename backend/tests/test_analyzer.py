from __future__ import annotations

import json
from pathlib import Path

from app.analyzer.core import AnalysisParams, analyze_video
from app.analyzer.motion import MotionParams
from app.config import get_settings


def test_analyzer_detects_movement(sample_video: Path, tmp_path: Path) -> None:
    settings = get_settings()
    params = AnalysisParams(
        sample_fps=2.0,
        width=320,
        masks=[],
        motion=MotionParams(
            threshold=0.002,
            min_area_ratio=0.001,
            warmup_frames=2,
            start_hits=2,
            end_gap=2,
            merge_gap_s=2,
            min_duration_s=0.5,
        ),
        decoder="cpu",
    )
    output = tmp_path / "analysis"
    result = analyze_video(sample_video, output, params, settings)
    assert result["summary"]["event_count"] >= 1
    assert (output / "result.json").exists()
    stored = json.loads((output / "result.json").read_text(encoding="utf-8"))
    assert stored["events"]
    assert stored["events"][0]["end_s"] > stored["events"][0]["start_s"]
