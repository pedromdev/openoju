#!/usr/bin/env python3
"""End-to-end smoke test against a running OpenOju instance.

Runs the whole first-use path with the standard library only:

    health -> setup -> login -> upload -> analyze -> job -> job log

Used by CI against a kind cluster and by anyone validating a new environment:

    kubectl -n openoju port-forward svc/openoju-openoju 8000:8000 &
    python3 scripts/e2e.py --token "$SETUP_TOKEN" --video /tmp/moving.mp4
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import mimetypes
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

DEFAULT_EMAIL = "owner@acme.com"
DEFAULT_PASSWORD = "senha-muito-segura-123"
DEFAULT_SLUG = "acme"


class Client:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def _request(self, method: str, path: str, **kwargs) -> tuple[int, bytes]:
        request = urllib.request.Request(
            f"{self.base_url}{path}", method=method, **kwargs
        )
        try:
            with self.opener.open(request, timeout=60) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def json(self, method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode()
            headers["Content-Type"] = "application/json"
        status, body = self._request(
            method, path, data=data, headers=self._csrf(headers)
        )
        try:
            parsed = json.loads(body or b"{}")
        except json.JSONDecodeError:
            parsed = {"raw": body.decode(errors="replace")}
        return status, parsed

    def _csrf(self, headers: dict[str, str]) -> dict[str, str]:
        token = next(
            (cookie.value for cookie in self.jar if cookie.name == "openoju_csrf"),
            None,
        )
        if token:
            headers["X-CSRF-Token"] = token
        return headers

    def upload(self, path: Path) -> tuple[int, dict]:
        boundary = f"----openoju{uuid.uuid4().hex}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        tail = f"\r\n--{boundary}--\r\n".encode()
        data = head + path.read_bytes() + tail
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        }
        status, body = self._request(
            "POST", "/api/v1/orgs/acme/videos/upload", data=data, headers=self._csrf(headers)
        )
        try:
            parsed = json.loads(body or b"{}")
        except json.JSONDecodeError:
            parsed = {"raw": body.decode(errors="replace")}
        return status, parsed

    def text(self, path: str) -> tuple[int, str]:
        status, body = self._request("GET", path, headers=self._csrf({}))
        return status, body.decode(errors="replace")


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
    assert status == 200, (status, payload)
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
    assert status == 201, (status, payload)
    print("setup concluído")


def login(client: Client, email: str, password: str) -> None:
    status, payload = client.json(
        "POST", "/api/v1/auth/login", {"email": email, "password": password}
    )
    assert status == 200, (status, payload)
    assert any(cookie.name == "openoju_csrf" for cookie in client.jar), "cookie CSRF ausente"
    print("login ok")


def analyze(client: Client, video_id: str) -> str:
    status, payload = client.json(
        "POST", f"/api/v1/orgs/acme/videos/{video_id}/analyze"
    )
    assert status == 200, (status, payload)
    return payload["id"]


def wait_job(client: Client, job_id: str, timeout_s: int = 900) -> dict:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        status, payload = client.json("GET", f"/api/v1/orgs/acme/jobs/{job_id}")
        assert status == 200, (status, payload)
        if payload.get("status") != last:
            print(f"job: {payload.get('status')} {payload.get('stage')} {payload.get('progress')}")
            last = payload.get("status")
        if payload.get("status") == "completed":
            return payload
        if payload.get("status") in {"failed", "canceled"}:
            raise SystemExit(f"job terminou como {payload.get('status')}: {payload.get('error')}")
        time.sleep(3)
    raise SystemExit("timeout aguardando o job")


def check_job_log(client: Client, job_id: str, reads: int) -> None:
    for attempt in range(reads):
        status, body = client.text(f"/api/v1/orgs/acme/jobs/{job_id}/log")
        assert status == 200, (attempt, status, body[:200])
        assert body.strip(), "log vazio"
        assert "job" in body, f"log inesperado: {body[:120]}"
    print(f"log do job ok em {reads} leitura(s)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test E2E do OpenOju")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", required=True, help="OJU_SETUP_TOKEN")
    parser.add_argument("--video", required=True, help="arquivo .mp4 de teste")
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--slug", default=DEFAULT_SLUG)
    parser.add_argument("--log-reads", type=int, default=3)
    args = parser.parse_args(argv)

    video = Path(args.video)
    if not video.exists():
        raise SystemExit(f"vídeo não encontrado: {video}")

    client = Client(args.base_url)
    wait_http(client)
    check_setup(client, args.token, args.email, args.password, args.slug)
    login(client, args.email, args.password)

    status, payload = client.upload(video)
    assert status == 201, (status, payload)
    video_id = payload["video"]["id"]
    print(f"upload ok: {video_id}")

    job_id = analyze(client, video_id)
    job = wait_job(client, job_id)
    print(f"job concluído: {job.get('message')}")

    check_job_log(client, job_id, args.log_reads)
    print("E2E ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
