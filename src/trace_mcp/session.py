"""로그인 세션 파일(~/.trace-mcp/session.json, 권한 600, Windows는 사용자 프로필 폴더 권한). 토큰은 이 파일에만 두고 출력하지 않는다."""

from __future__ import annotations

import json
import os
import tempfile
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
    if not path.parent.exists():  # 새로 만든 폴더만 700으로(이미 있는 폴더 권한은 건드리지 않음)
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)  # 동시에 만들어도 실패하지 않게
        os.chmod(path.parent, 0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")  # 고유 이름, 0600으로 독점 생성
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(asdict(session), f)
        os.replace(tmp, path)  # 쓰는 도중 끊겨도 기존 세션이 잘리지 않게 한 번에 바꾼다
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def clear(path: Path) -> None:
    path.unlink(missing_ok=True)
