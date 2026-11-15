#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Event, Video  # noqa: E402
from app.services.thumbnails import (  # noqa: E402
    refresh_event_thumbnail,
    thumbnail_timestamp,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Regenera thumbnails de eventos no ponto médio do intervalo."
    )
    parser.add_argument("--video-id", help="processa apenas um vídeo")
    parser.add_argument("--limit", type=int, default=0, help="limite total de eventos")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="mostra os pontos calculados sem gerar imagens",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    settings.ensure_dirs()
    db = SessionLocal()
    total = updated = failed = 0
    try:
        query = db.query(Video).order_by(Video.created_at.asc())
        if args.video_id:
            query = query.filter(Video.id == args.video_id)
        videos = query.all()
        for video in videos:
            events = (
                db.query(Event)
                .filter(Event.video_id == video.id)
                .order_by(Event.start_s.asc())
                .all()
            )
            first_thumb: str | None = None
            for event in events:
                if args.limit and total >= args.limit:
                    break
                at_s = thumbnail_timestamp(
                    event.start_s, event.end_s, video.duration_s
                )
                if args.dry_run:
                    print(
                        f"{video.filename} | {event.start_s:.1f}-{event.end_s:.1f}"
                        f" -> {at_s:.1f}s | {event.thumbnail_path}"
                    )
                    total += 1
                    updated += 1
                    continue
                if refresh_event_thumbnail(video, event, settings):
                    updated += 1
                    if first_thumb is None:
                        first_thumb = event.thumbnail_path
                else:
                    failed += 1
                    print(
                        f"falha: {video.filename} evento {event.id}",
                        file=sys.stderr,
                    )
                total += 1
            if first_thumb and not args.dry_run:
                video.thumbnail_path = first_thumb
            db.commit()
            if args.limit and total >= args.limit:
                break
    finally:
        db.close()
    print(
        f"eventos={total} atualizados={updated} falhas={failed}"
        + (" (dry-run)" if args.dry_run else "")
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
