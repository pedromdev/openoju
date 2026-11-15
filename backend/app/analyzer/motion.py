from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MotionParams:
    threshold: float = 0.003
    min_area_ratio: float = 0.0005
    warmup_frames: int = 5
    start_hits: int = 2
    end_gap: int = 3
    merge_gap_s: float = 5.0
    min_duration_s: float = 2.0
    max_duration_s: float = 300.0
    mog_history: int = 500
    var_threshold: float = 16.0
    detect_shadows: bool = True
    min_blob_area_ratio: float = 0.0005
    use_frame_diff: bool = True
    diff_threshold: int = 20
    illumination_mean_delta: float = 8.0
    illumination_diff_ratio: float = 0.35

    @classmethod
    def from_dict(cls, data: dict | None, defaults: "MotionParams | None" = None) -> "MotionParams":
        base = defaults or cls()
        values = {
            "threshold": base.threshold,
            "min_area_ratio": base.min_area_ratio,
            "warmup_frames": base.warmup_frames,
            "start_hits": base.start_hits,
            "end_gap": base.end_gap,
            "merge_gap_s": base.merge_gap_s,
            "min_duration_s": base.min_duration_s,
            "max_duration_s": base.max_duration_s,
            "mog_history": base.mog_history,
            "var_threshold": base.var_threshold,
            "detect_shadows": base.detect_shadows,
            "min_blob_area_ratio": base.min_blob_area_ratio,
            "use_frame_diff": base.use_frame_diff,
            "diff_threshold": base.diff_threshold,
            "illumination_mean_delta": base.illumination_mean_delta,
            "illumination_diff_ratio": base.illumination_diff_ratio,
        }
        for key in values:
            if data and key in data and data[key] is not None:
                values[key] = data[key]
        return cls(**values)


@dataclass
class FrameSignal:
    t: float
    score: float
    area_ratio: float
    bbox: list[int] | None = None


@dataclass
class MotionEvent:
    start_s: float
    end_s: float
    score: float
    peak_score: float
    bbox: list[int] | None
    peak_t: float
    frames: int = 0

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)

    def to_dict(self) -> dict:
        return {
            "start_s": round(self.start_s, 3),
            "end_s": round(self.end_s, 3),
            "duration_s": round(self.duration_s, 3),
            "score": round(self.score, 6),
            "peak_score": round(self.peak_score, 6),
            "bbox": self.bbox,
            "peak_t": round(self.peak_t, 3),
        }


def _event_from_window(
    samples: list[FrameSignal], start_idx: int, end_idx: int, interval: float
) -> MotionEvent:
    window = samples[start_idx : end_idx + 1]
    peak = max(window, key=lambda item: item.score)
    mean_score = sum(item.score for item in window) / max(1, len(window))
    return MotionEvent(
        start_s=samples[start_idx].t,
        end_s=samples[end_idx].t + interval,
        score=mean_score,
        peak_score=peak.score,
        bbox=peak.bbox,
        peak_t=peak.t,
        frames=len(window),
    )


def _split_long_event(event: MotionEvent, max_duration_s: float) -> list[MotionEvent]:
    if max_duration_s <= 0 or event.duration_s <= max_duration_s:
        return [event]
    pieces: list[MotionEvent] = []
    cursor = event.start_s
    while cursor < event.end_s:
        end = min(event.end_s, cursor + max_duration_s)
        pieces.append(
            MotionEvent(
                start_s=cursor,
                end_s=end,
                score=event.score,
                peak_score=event.peak_score,
                bbox=event.bbox,
                peak_t=min(max(event.peak_t, cursor), end),
                frames=event.frames,
            )
        )
        cursor = end
    return pieces


def aggregate_events(
    samples: list[FrameSignal], params: MotionParams, interval: float
) -> list[MotionEvent]:
    if not samples:
        return []
    interval = max(1e-6, interval)
    events: list[MotionEvent] = []
    active = False
    start_idx: int | None = None
    last_active_idx: int | None = None
    hits = 0

    for index, sample in enumerate(samples):
        is_active = (
            sample.score >= params.threshold
            and sample.area_ratio >= params.min_area_ratio
        )
        if not active:
            if is_active:
                hits += 1
                if hits >= max(1, params.start_hits):
                    active = True
                    start_idx = index - hits + 1
                    last_active_idx = index
            else:
                hits = 0
            continue

        if is_active:
            last_active_idx = index
        elif last_active_idx is not None:
            if index - last_active_idx >= max(1, params.end_gap):
                assert start_idx is not None
                events.append(
                    _event_from_window(samples, start_idx, last_active_idx, interval)
                )
                active = False
                start_idx = None
                last_active_idx = None
                hits = 0

    if active and start_idx is not None and last_active_idx is not None:
        events.append(_event_from_window(samples, start_idx, last_active_idx, interval))

    # Merge events separated by a short quiet interval.
    merged: list[MotionEvent] = []
    for event in events:
        if merged and event.start_s - merged[-1].end_s <= params.merge_gap_s:
            previous = merged[-1]
            if event.peak_score > previous.peak_score:
                previous.bbox = event.bbox
                previous.peak_t = event.peak_t
            previous.end_s = max(previous.end_s, event.end_s)
            previous.peak_score = max(previous.peak_score, event.peak_score)
            previous.score = max(previous.score, event.score)
            previous.frames += event.frames
        else:
            merged.append(event)

    filtered: list[MotionEvent] = []
    for event in merged:
        if event.duration_s < params.min_duration_s:
            continue
        filtered.extend(_split_long_event(event, params.max_duration_s))
    return filtered
