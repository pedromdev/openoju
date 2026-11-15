from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from sqlalchemy.orm import Session

from .config import BASE_DIR, Settings, get_settings
from .db import SessionLocal, init_db
from .models import CameraProfile, Event, Job, Organization, Video
from .services.ffmpeg import (
    FfmpegError,
    analysis_input,
    cut_clip,
    ensure_proxy,
    probe_video,
)
from .services.ingest import create_video_from_path, list_video_files
from .services.jobs import (
    claim_next_job,
    finish_job,
    progress,
    reset_stale_jobs,
)
from .services.outbox import emit
from .services.thumbnails import refresh_event_thumbnail
from .storage import StorageError, get_storage

_settings = get_settings()
_worker_id = f"{socket.gethostname()}-{os.getpid()}"
_stop = threading.Event()
_current_process: subprocess.Popen[str] | None = None
_process_lock = threading.Lock()


def _log(message: str) -> None:
    print(f"[worker {_worker_id}] {message}", flush=True)


def _profile_payload(db: Session, video: Video) -> dict:
    profile = None
    if video.profile_id:
        profile = (
            db.query(CameraProfile)
            .filter(
                CameraProfile.id == video.profile_id,
                CameraProfile.organization_id == video.organization_id,
            )
            .one_or_none()
        )
    if profile is None:
        profile = (
            db.query(CameraProfile)
            .filter(CameraProfile.organization_id == video.organization_id)
            .order_by(CameraProfile.created_at.asc())
            .first()
        )
    if profile is None:
        return {"masks": [], "roi": None, "settings": {}}
    return {
        "id": profile.id,
        "name": profile.name,
        "masks": profile.masks or [],
        "roi": profile.roi,
        "settings": profile.settings or {},
    }


def _job_dir(job_id: str) -> Path:
    path = _settings.jobs_dir / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_tail(path: Path, limit: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def _kill_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.terminate()
        except OSError:
            pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                process.kill()
            except OSError:
                pass


def _generate_artifacts(
    db: Session,
    video: Video,
    events: list[Event],
    job_dir: Path,
    source_path: Path,
) -> None:
    source = analysis_input(source_path, video.proxy_path)
    if not source.exists():
        return
    clips_dir = _settings.org_clips_dir(video.organization_id)
    clips_dir.mkdir(parents=True, exist_ok=True)
    storage = get_storage(_settings) if _settings.storage_backend == "s3" else None
    for index, event in enumerate(events):
        clip = clips_dir / f"{event.id}.mp4"
        clip_log = job_dir / f"clip-{index}.log"
        refresh_event_thumbnail(video, event, _settings)
        if cut_clip(source, clip, event.start_s, event.end_s, _settings, clip_log):
            event.clip_path = str(clip)
            if storage is not None:
                key = _settings.storage_key(video.organization_id, "clips", clip.name)
                storage.upload(clip, key)
                event.clip_storage_key = key
        if event.thumbnail_path and storage is not None:
            thumb = Path(event.thumbnail_path)
            if thumb.exists():
                key = _settings.storage_key(
                    video.organization_id, "thumbs", thumb.name
                )
                storage.upload(thumb, key)
                event.thumbnail_storage_key = key
        if index == 0 and event.thumbnail_path:
            video.thumbnail_path = event.thumbnail_path
            video.thumbnail_storage_key = event.thumbnail_storage_key
    db.commit()


def _import_result(
    db: Session,
    video: Video,
    job: Job,
    result_path: Path,
    job_dir: Path,
    source_path: Path,
) -> None:
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    raw_events = payload.get("events", [])
    # Replace prior results only after a successful analysis.
    db.query(Event).filter(
        Event.video_id == video.id,
        Event.organization_id == video.organization_id,
    ).delete()
    created: list[Event] = []
    for item in raw_events:
        event = Event(
            organization_id=video.organization_id,
            video_id=video.id,
            start_s=float(item.get("start_s", 0.0)),
            end_s=float(item.get("end_s", 0.0)),
            start_wallclock=item.get("start_wallclock"),
            end_wallclock=item.get("end_wallclock"),
            score=float(item.get("score", 0.0)),
            peak_score=float(item.get("peak_score", 0.0)),
            bbox=item.get("bbox"),
            label=item.get("label") or "movement",
            review_status="new",
        )
        db.add(event)
        created.append(event)
    db.flush()
    _generate_artifacts(db, video, created, job_dir, source_path)
    video.status = "ready"
    video.error = None
    job.result_path = str(result_path)
    for event in created:
        emit(
            db,
            organization_id=video.organization_id,
            event_type="event.created",
            aggregate_type="event",
            aggregate_id=event.id,
            payload={
                "id": event.id,
                "video_id": video.id,
                "start_s": event.start_s,
                "end_s": event.end_s,
                "score": event.score,
                "review_status": event.review_status,
            },
        )
    emit(
        db,
        organization_id=video.organization_id,
        event_type="analysis.completed",
        aggregate_type="video",
        aggregate_id=video.id,
        payload={
            "video_id": video.id,
            "job_id": job.id,
            "event_count": len(created),
        },
    )
    db.commit()
    _log(f"vídeo {video.id} ({video.organization_id}): {len(created)} evento(s)")


def _publish_job_log(db: Session, job_id: str, job_log: Path) -> None:
    """Copy the job log to object storage so any API replica can serve it.

    Local storage keeps using the filesystem; only the remote backend needs a
    shared copy, and doing it here removes the RWX volume requirement between
    the worker and the API.
    """
    settings = _settings
    if settings.storage_backend != "s3" or not job_log.exists():
        return
    job = db.get(Job, job_id)
    if job is None or job.log_key:
        return
    key = settings.job_log_key(job.organization_id, job.id)
    get_storage(settings).upload(job_log, key)
    job.log_key = key
    db.commit()


def _process_job(job_id: str) -> None:
    global _current_process
    db = SessionLocal()
    process: subprocess.Popen[str] | None = None
    job_dir = _job_dir(job_id)
    job_log = job_dir / "job.log"
    job: Job | None = None
    video: Video | None = None
    downloaded_source: Path | None = None
    try:
        job = db.get(Job, job_id)
        if job is None:
            return
        video = db.get(Video, job.video_id)
        if video is None:
            finish_job(db, job.id, status="failed", error="vídeo não encontrado")
            return
        if video.organization_id != job.organization_id:
            finish_job(
                db,
                job.id,
                status="failed",
                error="violação de tenancy: job e vídeo em organizações diferentes",
            )
            return
        job.log_path = str(job_log)
        progress(db, job.id, stage="prepare", value=0.02, message="inspecionando vídeo")
        _log(f"job {job.id}: preparando {video.filename} ({video.organization_id})")
        _settings.ensure_org_dirs(video.organization_id)

        if video.source_path:
            source_path = Path(video.source_path)
        else:
            if not video.storage_key:
                finish_job(
                    db,
                    job.id,
                    status="failed",
                    error="vídeo sem caminho local nem storage_key",
                )
                return
            suffix = Path(video.filename).suffix or ".mp4"
            source_path = job_dir / f"source{suffix}"
            progress(db, job.id, stage="download", value=0.02, message="baixando original")
            try:
                get_storage(_settings).download(video.storage_key, source_path)
            except StorageError as exc:
                raise FfmpegError(f"falha ao baixar original do storage: {exc}") from exc
            downloaded_source = source_path

        probe = probe_video(source_path, _settings)
        video.duration_s = video.duration_s or probe.duration_s
        video.fps = video.fps or probe.fps
        video.width = video.width or probe.width
        video.height = video.height or probe.height
        video.video_codec = video.video_codec or probe.video_codec
        video.audio_codec = video.audio_codec or probe.audio_codec
        video.recorded_at = video.recorded_at or probe.recorded_at
        db.commit()

        proxy = _settings.org_proxy_dir(video.organization_id) / f"{video.id}.mp4"
        progress(db, job.id, stage="proxy", value=0.05, message="gerando proxy MP4")
        mode = ensure_proxy(
            source_path, proxy, _settings, probe, job_dir / "proxy.log"
        )
        video.proxy_path = str(proxy)
        if _settings.storage_backend == "s3":
            key = _settings.storage_key(video.organization_id, "proxy", proxy.name)
            get_storage(_settings).upload(proxy, key)
            video.proxy_storage_key = key
        db.commit()
        progress(
            db,
            job.id,
            stage="proxy",
            value=0.25,
            message=f"proxy pronto ({mode})",
        )

        profile_path = job_dir / "profile.json"
        profile_path.write_text(
            json.dumps(_profile_payload(db, video), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        input_path = analysis_input(source_path, video.proxy_path)
        progress(db, job.id, stage="analyze", value=0.25, message="analisando movimento")

        env = dict(os.environ)
        env["PYTHONPATH"] = str(BASE_DIR / "backend") + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
        )
        env["PYTHONUNBUFFERED"] = "1"
        cmd = [
            sys.executable,
            "-m",
            "app.analyzer.cli",
            "--input",
            str(input_path),
            "--output",
            str(job_dir),
            "--profile",
            str(profile_path),
            "--sample-fps",
            str(_settings.sample_fps),
            "--width",
            str(_settings.analysis_width),
            "--decoder",
            "auto",
            "--progress-ndjson",
        ]
        if video.recorded_at:
            cmd += ["--recorded-at", video.recorded_at]
        with job_log.open("a", encoding="utf-8") as log:
            log.write("\n$ " + " ".join(cmd) + "\n\n")
            log.flush()
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=log,
                text=True,
                bufsize=1,
                env=env,
                start_new_session=True,
            )
            with _process_lock:
                _current_process = process
            assert process.stdout is not None
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("{"):
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    raw_progress = payload.get("progress")
                    mapped = None
                    if raw_progress is not None:
                        mapped = 0.25 + 0.70 * float(raw_progress)
                    progress(
                        db,
                        job.id,
                        stage=payload.get("stage") or "analyze",
                        value=mapped,
                        message=payload.get("message"),
                    )
                db.expire_all()
                current = db.get(Job, job.id)
                if current is not None and current.status == "canceled":
                    _log(f"job {job.id}: cancelado pelo usuário")
                    _kill_process(process)
                    finish_job(db, job.id, status="canceled", message="cancelado")
                    video.status = "uploaded"
                    db.commit()
                    return
            returncode = process.wait()
            with _process_lock:
                _current_process = None

        if returncode != 0:
            tail = _read_tail(job_log)
            raise FfmpegError(f"analyzer retornou código {returncode}: {tail}")

        result_path = job_dir / "result.json"
        if not result_path.exists():
            raise FfmpegError("analyzer terminou sem result.json")
        progress(db, job.id, stage="artifacts", value=0.96, message="gerando clipes")
        _import_result(db, video, job, result_path, job_dir, source_path)
        finish_job(
            db,
            job.id,
            status="completed",
            message="análise concluída",
            result_path=str(result_path),
        )
        _log(f"job {job.id}: concluído")
    except Exception as exc:  # noqa: BLE001 - worker must persist any failure
        _log(f"job {job_id}: falhou: {exc}")
        tail = _read_tail(job_log)
        finish_job(
            db,
            job_id,
            status="failed",
            error=f"{exc}\n\n{tail}".strip(),
        )
        job = db.get(Job, job_id)
        if job is not None:
            video = db.get(Video, job.video_id)
            if video is not None:
                video.status = "failed"
                video.error = str(exc)[:4000]
                emit(
                    db,
                    organization_id=video.organization_id,
                    event_type="analysis.failed",
                    aggregate_type="video",
                    aggregate_id=video.id,
                    payload={
                        "video_id": video.id,
                        "job_id": job.id,
                        "error": str(exc)[:2000],
                    },
                )
                db.commit()
    finally:
        if process is not None and process.poll() is None:
            _kill_process(process)
        with _process_lock:
            _current_process = None
        if downloaded_source is not None:
            downloaded_source.unlink(missing_ok=True)
        try:
            _publish_job_log(db, job_id, job_log)
        except Exception as exc:  # noqa: BLE001 - never break the worker loop
            _log(f"job {job_id}: falha ao publicar log: {exc}")
            try:
                db.rollback()
            except Exception:  # noqa: BLE001 - connection may already be gone
                pass
        db.close()


class FolderWatcher(threading.Thread):
    """Optional single-organization folder ingestion.

    The watcher requires ``OJU_WATCH_ORG_SLUG``. Without it, ingestion by
    folder stays disabled so files can never land in an ambiguous tenant.
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(name="folder-watcher", daemon=True)
        self.settings = settings
        self._seen: dict[str, tuple[int, float]] = {}
        self.organization_id: str | None = None

    def _resolve_org(self, db: Session) -> str | None:
        if not self.settings.watch_org_slug:
            return None
        organization = (
            db.query(Organization)
            .filter(Organization.slug == self.settings.watch_org_slug)
            .one_or_none()
        )
        return organization.id if organization else None

    def run(self) -> None:
        root = self.settings.effective_watch_dir
        if not self.settings.watch_org_slug:
            _log(
                "watcher desabilitado: defina OJU_WATCH_ORG_SLUG para habilitar"
            )
            return
        _log(f"observando pasta {root} para org {self.settings.watch_org_slug}")
        while not _stop.is_set():
            try:
                self._scan(root)
            except Exception as exc:  # noqa: BLE001 - watcher must stay alive
                _log(f"watcher: erro: {exc}")
            _stop.wait(self.settings.watch_interval_s)

    def _scan(self, root: Path) -> None:
        if not root.exists():
            return
        db = SessionLocal()
        try:
            organization_id = self._resolve_org(db)
            if organization_id is None:
                _log(
                    f"watcher: organização {self.settings.watch_org_slug!r} não encontrada"
                )
                return
            for path in list_video_files(root, recursive=True):
                key = str(path.resolve())
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if stat.st_size < 1024 * 1024:
                    continue
                age = time.time() - stat.st_mtime
                if age < self.settings.watch_min_age_s:
                    continue
                existing = (
                    db.query(Video)
                    .filter(
                        Video.organization_id == organization_id,
                        Video.source_path == key,
                    )
                    .first()
                )
                if existing is not None:
                    continue
                previous = self._seen.get(key)
                current = (stat.st_size, stat.st_mtime)
                if previous != current:
                    self._seen[key] = current
                    continue
                try:
                    video, _job = create_video_from_path(
                        db, path, organization_id=organization_id, settings=self.settings
                    )
                    _log(f"watcher: importado {video.filename}")
                    self._seen.pop(key, None)
                except Exception as exc:  # noqa: BLE001
                    _log(f"watcher: falha ao importar {path}: {exc}")
        finally:
            db.close()


def _signal_handler(signum, _frame) -> None:  # type: ignore[no-untyped-def]
    _log(f"recebido sinal {signum}; encerrando")
    _stop.set()
    with _process_lock:
        process = _current_process
    if process is not None:
        _kill_process(process)


def main() -> int:
    if _settings.is_sqlite:
        init_db()
    db = SessionLocal()
    try:
        reset_stale_jobs(db, stale_after_s=_settings.job_timeout_s)
    finally:
        db.close()

    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)
    FolderWatcher(_settings).start()
    _log(f"worker iniciado ({_settings.effective_database_url.split('@')[-1]})")

    while not _stop.is_set():
        db = SessionLocal()
        try:
            job = claim_next_job(db, _worker_id)
        except Exception as exc:  # noqa: BLE001
            _log(f"erro ao buscar job: {exc}")
            db.rollback()
            job = None
        finally:
            db.close()
        if job is None:
            _stop.wait(2.0)
            continue
        _process_job(job.id)

    _log("worker encerrado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
