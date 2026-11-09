"""한 줄 설치 스크립트(install/agent.sh): 코드 검사와, 받은 소스로 에이전트를 실제로 부르는지."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "install" / "agent.sh"

pytestmark = pytest.mark.skipif(sys.platform == "win32" or shutil.which("sh") is None, reason="POSIX sh 필요")


def _sh(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    # curl | sh -s 처럼 스크립트를 표준 입력으로 준다
    return subprocess.run(["sh", "-s", *args], check=False, input=SCRIPT.read_text(encoding="utf-8"),
                          capture_output=True,
                          text=True, env=env, timeout=300)


def test_6자리가_아닌_코드는_받기_전에_멈춘다(tmp_path: Path) -> None:
    result = _sh(["12ab"], {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert result.returncode == 1
    assert "6자리" in result.stderr
    assert not (tmp_path / ".trace-agent").exists()


@pytest.mark.skipif(sys.platform != "linux", reason="macOS CI에서는 실제 수집·벤치마크가 돌아 오래 걸린다")
def test_받은_소스를_풀어_에이전트를_부른다(tmp_path: Path) -> None:
    archive = tmp_path / "agent.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(ROOT / "src", arcname="agent-develop/src")
    home = tmp_path / "home"
    env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "HOME": str(tmp_path),
           "TRACE_AGENT_HOME": str(home), "TRACE_AGENT_SRC": archive.as_uri()}
    result = _sh([], env)
    assert (home / "src" / "trace_agent" / "__main__.py").exists()
    assert "기기 정보를 읽는 중" in result.stdout
    assert (home / "trace-diagnostics.json").exists()
