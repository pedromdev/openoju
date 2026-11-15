from __future__ import annotations

import numpy as np

from app.analyzer.core import apply_masks
from app.analyzer.motion import FrameSignal, MotionParams, aggregate_events


def test_aggregate_single_event() -> None:
    params = MotionParams(
        threshold=0.01,
        min_area_ratio=0.001,
        start_hits=2,
        end_gap=2,
        merge_gap_s=2,
        min_duration_s=1,
        warmup_frames=0,
    )
    samples = [
        FrameSignal(t=0, score=0.0, area_ratio=0.0),
        FrameSignal(t=1, score=0.05, area_ratio=0.02),
        FrameSignal(t=2, score=0.06, area_ratio=0.02),
        FrameSignal(t=3, score=0.07, area_ratio=0.02),
        FrameSignal(t=4, score=0.0, area_ratio=0.0),
        FrameSignal(t=5, score=0.0, area_ratio=0.0),
        FrameSignal(t=6, score=0.0, area_ratio=0.0),
    ]
    events = aggregate_events(samples, params, interval=1.0)
    assert len(events) == 1
    event = events[0]
    assert event.start_s == 1
    assert event.end_s == 4
    assert event.peak_score == 0.07


def test_merge_close_events() -> None:
    params = MotionParams(
        threshold=0.01,
        min_area_ratio=0.001,
        start_hits=2,
        end_gap=1,
        merge_gap_s=10,
        min_duration_s=1,
        warmup_frames=0,
    )
    samples = [
        FrameSignal(t=0, score=0.05, area_ratio=0.02),
        FrameSignal(t=1, score=0.05, area_ratio=0.02),
        FrameSignal(t=2, score=0.0, area_ratio=0.0),
        FrameSignal(t=3, score=0.0, area_ratio=0.0),
        FrameSignal(t=4, score=0.05, area_ratio=0.02),
        FrameSignal(t=5, score=0.05, area_ratio=0.02),
        FrameSignal(t=6, score=0.0, area_ratio=0.0),
        FrameSignal(t=7, score=0.0, area_ratio=0.0),
    ]
    events = aggregate_events(samples, params, interval=1.0)
    assert len(events) == 1
    assert events[0].start_s == 0
    assert events[0].end_s == 6


def test_apply_masks_normalized() -> None:
    frame = np.full((100, 200), 255, dtype=np.uint8)
    apply_masks(frame, [{"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.2}])
    assert frame[:20, :100].max() == 0
    assert frame[30:, 110:].min() == 255
