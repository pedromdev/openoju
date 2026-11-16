#!/usr/bin/env python3
"""End-to-end smoke test against a running OpenOju instance.

Covers the paths that only exist once the app runs behind a real API, worker
and object storage:

  1. health, setup, login (cookie + CSRF)
  2. simple multipart upload (session auth)
  3. chunked upload via /uploads (session auth)
  4. presigned multipart upload via /ingest (API key)
  5. analysis + job polling + job log served from object storage
  6. media endpoints: stream, thumbnails, events, clip
  7. optional shared login rate limit (--rate-limit)

Standard library only. Used by CI against kind and by anyone validating a new
environment:

    kubectl -n openoju port-forward svc/openoju-openoju 8000:8000 &
    python3 scripts/e2e.py --token "$SETUP_TOKEN" --video /tmp/moving.mp4
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import mimetypes
import math
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_EMAIL = "owner@acme.com"
DEFAULT_PASSWORD = "senha-muito-segura-123"
DEFAULT_SLUG = "acme"


class E2EFailure(AssertionError):
    pass


def expect(condition: bool, message: str) -> None:
    if not condition:
        raise E2EFailure(message)


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        if not url.startswith("http"):
            url = f"{self.base_url}{url}"
        request = urllib.request.Request(
            url, method=method, data=data, headers=headers or {}
        )
        try:
            with self.opener.open(request, timeout=180) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def _csrf(self, headers: dict[str, str]) -> dict[str, str]:
        token = next(
            (cookie.value for cookie in self.jar if cookie.name == "openoju_csrf"),
            None,
        )
        if token:
            headers["X-CSRF-Token"] = token
        return headers

    def json(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        bearer: str | None = None,
        csrf: bool = True,
    ) -> tuple[int, dict]:
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        elif csrf:
            headers = self._csrf(headers)
        status, _, body = self._request(method, path, data=data, headers=headers)
        try:
            parsed = json.loads(body or b"{}")
        except json.JSONDecodeError:
            parsed = {"raw": body.decode(errors="replace")}
        return status, parsed

    def put(
        self, path: str, data: bytes, *, bearer: str | None = None, raw: bool = False
    ) -> tuple[int, dict[str, str], bytes]:
        headers = {"Content-Type": "application/octet-stream"}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        elif not raw:
            headers = self._csrf(headers)
        return self._request("PUT", path, data=data, headers=headers)

    def get(self, path: str) -> tuple[int, dict[str, str], bytes]:
        return self._request("GET", path, headers=self._csrf({}))

    def upload_multipart(self, path: Path) -> tuple[int, dict]:
        boundary = f"----openoju{uuid.uuid4().hex}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        }
        status, _, body = self._request(
            "POST",
            f"/api/v1/orgs/{DEFAULT_SLUG}/videos/upload",
            data=head + path.read_bytes() + tail,
            headers=self._csrf(headers),
        )
        try:
            parsed = json.loads(body or b"{}")
        except json.JSONDecodeError:
            parsed = {"raw": body.decode(errors="replace")}
        return status, parsed


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def wait_http(client: Client, attempts: int = 60) -> None:
    for attempt in range(1, attempts + 1):
        try:
            status, payload = client.json("GET", "/api/health")
            if status == 200 and payload.get("status") in {"ok", "degraded"}:
                print(f"health ok ({payload.get('status')})")
                return
        except urllib.error.URLError:
            pass
        print(f"aguardando API ({attempt}/{attempts})")
        time.sleep(3)
    raise SystemExit("API não respondeu a tempo")


def check_setup(client: Client, token: str, email: str, password: str, slug: str) -> None:
    status, payload = client.json("GET", "/api/v1/auth/setup/status")
    expect(status == 200, f"setup/status: {status} {payload}")
    if not payload.get("setup_required", True):
        print("setup já concluído; seguindo para login")
        return
    status, payload = client.json(
        "POST",
        "/api/v1/auth/setup",
        {
            "token": token,
            "organization_name": "Acme",
            "organization_slug": slug,
            "owner_email": email,
            "owner_password": password,
            "owner_display_name": "Owner Acme",
        },
    )
    expect(status == 201, f"setup: {status} {payload}")
    print("setup concluído")


def login(client: Client, email: str, password: str) -> None:
    status, payload = client.json(
        "POST", "/api/v1/auth/login", {"email": email, "password": password}
    )
    expect(status == 200, f"login: {status} {payload}")
    expect(
        any(cookie.name == "openoju_csrf" for cookie in client.jar),
        "cookie CSRF ausente",
    )
    print("login ok")


def wait_job(client: Client, job_id: str, timeout_s: int = 900) -> dict:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        status, payload = client.json(
            "GET", f"/api/v1/orgs/{DEFAULT_SLUG}/jobs/{job_id}"
        )
        expect(status == 200, f"job {job_id}: {status} {payload}")
        if payload.get("status") != last:
            print(
                f"  job {job_id[:8]}: {payload.get('status')} "
                f"{payload.get('stage')} {payload.get('progress')}"
            )
            last = payload.get("status")
        if payload.get("status") == "completed":
            return payload
        if payload.get("status") in {"failed", "canceled"}:
            raise E2EFailure(
                f"job {job_id} terminou como {payload.get('status')}: {payload.get('error')}"
            )
        time.sleep(3)
    raise E2EFailure(f"timeout aguardando job {job_id}")


def job_for(
    client: Client, video_id: str, payload: dict, label: str
) -> dict:
    job = payload.get("job")
    if job:
        job_id = job["id"]
    else:
        status, job = client.json(
            "POST", f"/api/v1/orgs/{DEFAULT_SLUG}/videos/{video_id}/analyze"
        )
        expect(status == 200, f"{label} analyze: {status} {job}")
        job_id = job["id"]
    print(f"{label}: upload ok, job {job_id[:8]}")
    return wait_job(client, job_id)


def simple_upload(client: Client, video: Path) -> tuple[str, dict]:
    status, payload = client.upload_multipart(video)
    expect(status == 201, f"upload simples: {status} {payload}")
    video_id = payload["video"]["id"]
    job = job_for(client, video_id, payload, "upload simples")
    return video_id, job


def chunked_upload(
    client: Client, video: Path, *, expect_multipart: bool
) -> tuple[str, dict, int]:
    data = video.read_bytes()
    status, init = client.json(
        "POST",
        f"/api/v1/orgs/{DEFAULT_SLUG}/uploads/init",
        {"filename": video.name, "size": len(data)},
    )
    expect(status == 201, f"uploads/init: {status} {init}")
    part_size = init["part_size"]
    total = init["total_parts"]
    expect(
        total == math.ceil(len(data) / part_size),
        f"total_parts inesperado: {total} para {len(data)} bytes",
    )
    if expect_multipart:
        expect(total >= 2, f"esperava multipart, veio {total} parte(s)")
    for number in range(1, total + 1):
        chunk = data[(number - 1) * part_size : number * part_size]
        status, _, body = client.put(
            f"/api/v1/orgs/{DEFAULT_SLUG}/uploads/{init['upload_id']}"
            f"/parts/{number}",
            chunk,
        )
        expect(status == 200, f"parte {number}: {status} {body[:200]}")
    status, payload = client.json(
        "POST",
        f"/api/v1/orgs/{DEFAULT_SLUG}/uploads/{init['upload_id']}/complete",
    )
    expect(status == 200, f"uploads/complete: {status} {payload}")
    video_id = payload["video"]["id"]
    job = job_for(client, video_id, payload, f"chunked ({total} parte(s))")
    return video_id, job, total


def create_api_key(client: Client) -> str:
    status, payload = client.json(
        "POST",
        f"/api/v1/orgs/{DEFAULT_SLUG}/api-keys",
        {"name": "e2e", "scopes": ["ingest:write"]},
    )
    expect(status == 201, f"api-keys: {status} {payload}")
    return payload["key"]


def presigned_upload(
    client: Client, video: Path, api_key: str, *, expect_multipart: bool
) -> tuple[str, dict, int, str]:
    data = video.read_bytes()
    status, init = client.json(
        "POST",
        "/api/v1/ingest/uploads",
        {"filename": video.name, "size": len(data)},
        bearer=api_key,
    )
    expect(status == 201, f"ingest/uploads: {status} {init}")
    part_size = init["part_size"]
    total = init["total_parts"]
    if expect_multipart:
        expect(total >= 2, f"esperava multipart no presigned, veio {total} parte(s)")
    urls = init.get("part_urls") or []
    mode = "presigned" if urls else "api"
    for number in range(1, total + 1):
        chunk = data[(number - 1) * part_size : number * part_size]
        if urls:
            status, _, body = client.put(urls[number - 1], chunk, raw=True)
        else:
            status, _, body = client.put(
                f"/api/v1/ingest/uploads/{init['upload_id']}/parts/{number}",
                chunk,
                bearer=api_key,
            )
        expect(status == 200, f"parte {number} ({mode}): {status} {body[:200]}")
    status, payload = client.json(
        "POST",
        f"/api/v1/ingest/uploads/{init['upload_id']}/complete",
        bearer=api_key,
    )
    expect(status == 200, f"ingest/complete: {status} {payload}")
    video_id = payload["video"]["id"]
    job = job_for(client, video_id, payload, f"presigned ({mode}, {total} parte(s))")
    return video_id, job, total, mode


def check_job_log(client: Client, job_id: str, reads: int) -> None:
    for attempt in range(reads):
        status, headers, body = client.get(
            f"/api/v1/orgs/{DEFAULT_SLUG}/jobs/{job_id}/log"
        )
        expect(status == 200, f"log ({attempt}): {status} {body[:120]}")
        text = body.decode(errors="replace")
        expect(bool(text.strip()), "log vazio")
        expect("job" in text, f"log inesperado: {text[:120]}")
    print(f"log do job ok em {reads} leitura(s)")


def check_media(client: Client, video_id: str) -> None:
    base = f"/api/v1/orgs/{DEFAULT_SLUG}"
    status, headers, body = client.get(f"{base}/videos/{video_id}/thumbnail")
    expect(status == 200, f"thumbnail: {status}")
    expect(
        headers.get("Content-Type", "").startswith("image/"),
        f"thumbnail content-type: {headers.get('Content-Type')}",
    )

    status, headers, body = client.get(f"{base}/videos/{video_id}/stream")
    expect(status == 200, f"stream: {status}")
    expect(
        "video/" in headers.get("Content-Type", ""),
        f"stream content-type: {headers.get('Content-Type')}",
    )
    expect(len(body) > 0, "stream vazio")

    status, events = client.json("GET", f"{base}/videos/{video_id}/events")
    expect(status == 200, f"events: {status} {events}")
    expect(isinstance(events, list) and events, "nenhum evento gerado pela análise")
    event = events[0]
    for suffix in ("thumbnail", "clip"):
        status, headers, body = client.get(f"{base}/events/{event['id']}/{suffix}")
        expect(status == 200, f"evento {suffix}: {status}")
        expect(len(body) > 0, f"evento {suffix} vazio")
    print(f"mídia ok: stream, thumbnail, {len(events)} evento(s), clipe")


def check_rate_limit(client: Client, attempts: int) -> None:
    status = 0
    for _ in range(attempts):
        status, payload = client.json(
            "POST",
            "/api/v1/auth/login",
            {"email": "rate-limit-probe@example.com", "password": "errada"},
            csrf=False,
        )
    expect(status == 429, f"rate limit não disparou (último status {status})")
    print(f"rate limit ok após {attempts} tentativas")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test E2E do OpenOju")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", required=True, help="OJU_SETUP_TOKEN")
    parser.add_argument("--video", required=True, help="arquivo .mp4 de teste")
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--log-reads", type=int, default=3)
    parser.add_argument(
        "--expect-multipart",
        action="store_true",
        help="falha se o upload tiver apenas 1 parte (use com part size pequeno)",
    )
    parser.add_argument("--skip-simple", action="store_true")
    parser.add_argument("--skip-chunked", action="store_true")
    parser.add_argument("--skip-presigned", action="store_true")
    parser.add_argument("--skip-media", action="store_true")
    parser.add_argument(
        "--rate-limit",
        action="store_true",
        help="testa o 429 do login (usa e-mail descartável; requer backend postgres em multi-réplica)",
    )
    args = parser.parse_args(argv)

    video = Path(args.video)
    if not video.exists():
        raise SystemExit(f"vídeo não encontrado: {video}")

    client = Client(args.base_url)
    wait_http(client)
    check_setup(client, args.token, args.email, args.password, DEFAULT_SLUG)
    login(client, args.email, args.password)

    analyzed: str | None = None
    if not args.skip_simple:
        analyzed, job = simple_upload(client, video)
        check_job_log(client, job["id"], args.log_reads)
    if not args.skip_chunked:
        chunked, _job, parts = chunked_upload(
            client, video, expect_multipart=args.expect_multipart
        )
        analyzed = analyzed or chunked
        print(f"chunked ok ({parts} parte(s))")
    if not args.skip_presigned:
        api_key = create_api_key(client)
        presigned, _job, parts, mode = presigned_upload(
            client, video, api_key, expect_multipart=args.expect_multipart
        )
        analyzed = analyzed or presigned
        print(f"presigned ok ({mode}, {parts} parte(s))")
    if not args.skip_media and analyzed:
        check_media(client, analyzed)
    if args.rate_limit:
        check_rate_limit(client, attempts=12)

    print("E2E ok")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except E2EFailure as exc:
        print(f"falha: {exc}", file=sys.stderr)
        sys.exit(1)
