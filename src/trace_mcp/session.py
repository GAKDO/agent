"""로그인 세션 파일(~/.trace-mcp/session.json, 권한 600). 토큰은 이 파일에만 두고 출력하지 않는다."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def default_path() -> Path:
    return Path(os.environ.get("TRACE_MCP_HOME", Path.home() / ".trace-mcp")) / "session.json"


@dataclass
class Session:
    access_token: str
    refresh_token: str | None = None


def load(path: Path) -> Session | None:
    try:
        data = json.loads(path.read_text())
        return Session(access_token=data["access_token"], refresh_token=data.get("refresh_token"))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save(path: Path, session: Session) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(asdict(session), f)
    os.chmod(path, 0o600)  # 이미 있던 파일도 600으로


def clear(path: Path) -> None:
    path.unlink(missing_ok=True)
