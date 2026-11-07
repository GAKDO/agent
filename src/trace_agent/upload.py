"""페어링 코드 → AGENT JWT 교환과 진단 JSON 업로드. 토큰은 메모리에만 두고 출력하지 않는다."""

from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

Post = Callable[[str, dict[str, Any], dict[str, str]], tuple[int, dict[str, Any]]]
Sleep = Callable[[float], None]

RATE_LIMIT_RETRIES = 2  # 429면 Retry-After만큼 기다렸다가 두 번까지 다시 시도(contracts auth-server 1.0.0)
MAX_WAIT_SEC = 60.0
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class Pairing:
    """페어링 코드 교환 결과. device_serial은 관리자가 코드를 만들 때 고른 렌탈 기기 시리얼(AGENT JWT 클레임과 같음)."""
    token: str
    device_serial: str | None


def insecure(api: str) -> bool:
    """토큰이 평문으로 나가는 주소인지. 내 컴퓨터(localhost)에서 시험할 때는 http도 괜찮다."""
    url = urllib.parse.urlparse(api)
    return url.scheme != "https" and (url.hostname or "") not in _LOCAL_HOSTS


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
            body = json.loads(err.read() or b"{}")
        except ValueError:  # JSONDecodeError·UnicodeDecodeError 모두
            body = {}
        except (OSError, http.client.HTTPException) as read_err:
            # 오류 본문을 읽다 끊겨도 같은 키로 다시 올릴 수 있게 저장 경로로 넘긴다
            raise UploadError(0, "BAD_RESPONSE", str(read_err)) from read_err
        if not isinstance(body, dict):
            body = {}
        if (retry := err.headers.get("Retry-After")) is not None:
            body.setdefault("retryAfter", retry)  # 429 대기 시간을 호출한 쪽에 넘긴다
        return err.code, body
    except urllib.error.URLError as err:
        raise UploadError(0, "UNREACHABLE", str(err.reason)) from err
    except (OSError, ValueError, http.client.HTTPException) as err:
        # 응답을 읽다 끊기거나(시간 초과·IncompleteRead 포함) 본문이 JSON·UTF-8이 아니면, 서버가 처리했을 수 있으니 같은 키로 다시 올리게 한다
        raise UploadError(0, "BAD_RESPONSE", str(err)) from err


def _fail(status: int, body: dict[str, Any]) -> UploadError:
    return UploadError(status, str(body.get("code") or "UNKNOWN"), str(body.get("detail") or ""))


def _wait_sec(body: dict[str, Any]) -> float:
    try:
        return min(MAX_WAIT_SEC, max(1.0, float(body.get("retryAfter", 5))))
    except (TypeError, ValueError):
        return 5.0


def exchange(api: str, code: str, post: Post, sleep: Sleep = time.sleep,
             notify: Callable[[str], None] | None = None) -> Pairing:
    """코드 → AGENT JWT. 서버가 잠시 막으면(429) Retry-After만큼 기다렸다 다시 시도한다."""
    for attempt in range(RATE_LIMIT_RETRIES + 1):
        status, body = post(f"{api}/api/v1/auth/pairing-codes/exchange", {"code": code}, {})
        if status == 429 and attempt < RATE_LIMIT_RETRIES:
            wait = _wait_sec(body)
            if notify:
                notify(f"서버가 잠시 막았어요. {wait:.0f}초 뒤 다시 시도해요.")
            sleep(wait)
            continue
        if status != 200 or not body.get("accessToken"):
            raise _fail(status, body)
        return Pairing(str(body["accessToken"]), str(body["deviceSerial"]) if body.get("deviceSerial") else None)
    raise _fail(429, {"code": "RATE_LIMITED"})  # 반복문이 늘 return/raise로 끝나지만 타입 검사를 위해


def send(api: str, token: str, doc: dict[str, Any], post: Post, idempotency_key: str | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": idempotency_key or str(uuid.uuid4())}
    status, body = post(f"{api}/api/v1/diagnostics/runs", doc, headers)
    if status not in (200, 201):
        raise _fail(status, body)
    return body
