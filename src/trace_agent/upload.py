"""페어링 코드 → AGENT JWT 교환과 진단 JSON 업로드. 토큰은 메모리에만 두고 출력하지 않는다."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from typing import Any

Post = Callable[[str, dict[str, Any], dict[str, str]], tuple[int, dict[str, Any]]]


class UploadError(Exception):
    def __init__(self, status: int, code: str, detail: str = "") -> None:
        super().__init__(f"HTTP {status} {code}" + (f": {detail}" if detail else ""))
        self.status, self.code = status, code


def http_post(url: str, body: dict[str, Any], headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as err:
        try:
            return err.code, json.loads(err.read() or b"{}")
        except json.JSONDecodeError:
            return err.code, {}
    except urllib.error.URLError as err:
        raise UploadError(0, "UNREACHABLE", str(err.reason)) from err


def _fail(status: int, body: dict[str, Any]) -> UploadError:
    return UploadError(status, str(body.get("code") or "UNKNOWN"), str(body.get("detail") or ""))


def exchange(api: str, code: str, post: Post) -> str:
    status, body = post(f"{api}/api/v1/auth/pairing-codes/exchange", {"code": code}, {})
    if status != 200 or not body.get("accessToken"):
        raise _fail(status, body)
    return str(body["accessToken"])


def send(api: str, token: str, doc: dict[str, Any], post: Post, idempotency_key: str | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": idempotency_key or str(uuid.uuid4())}
    status, body = post(f"{api}/api/v1/diagnostics/runs", doc, headers)
    if status not in (200, 201):
        raise _fail(status, body)
    return body
