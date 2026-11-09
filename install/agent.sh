#!/bin/sh
# TRACE 진단 에이전트 한 줄 설치·실행 (macOS. 수집기가 macOS용이라 Linux는 받기·실행만 된다)
#
#   curl -fsSL https://gakdo.site/agent.sh | sh -s 123456
#
# 하는 일: 에이전트 소스를 GitHub에서 받아 ~/.trace-agent에 풀고(외부 패키지가 없어 pip가 필요 없다),
# TRACE_API_URL을 채워 `python3 -m trace_agent run --code <코드>`를 실행한다.
# 결과를 화면에 보여 주고 y를 넣어야 올린다. 비밀값은 이 파일에 없다(페어링 코드는 5분짜리 일회용).
#
# 바꿀 수 있는 값(환경 변수): TRACE_API_URL(기본 https://gakdo.site), TRACE_AGENT_REF(기본 develop),
# TRACE_AGENT_HOME(기본 ~/.trace-agent), TRACE_AGENT_SRC(소스 tar.gz 주소)
set -eu

CODE="${1:-}"
API="${TRACE_API_URL:-https://gakdo.site}"
REF="${TRACE_AGENT_REF:-develop}"
HOME_DIR="${TRACE_AGENT_HOME:-$HOME/.trace-agent}"
SRC="${TRACE_AGENT_SRC:-https://codeload.github.com/GAKDO/agent/tar.gz/refs/heads/$REF}"

say() { printf '%s\n' "$*"; }
die() { printf '%s\n' "$*" >&2; exit 1; }

case "$CODE" in
  "") ;;
  [0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) die "페어링 코드는 6자리 숫자예요. 예: curl -fsSL https://gakdo.site/agent.sh | sh -s 123456" ;;
esac

# 파이썬 3.11 이상 찾기(macOS 기본 /usr/bin/python3는 3.9라 안 된다)
PY=""
for c in python3.13 python3.12 python3.11 python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY="$c"
    break
  fi
done
if [ -z "$PY" ]; then
  say "파이썬 3.11 이상이 필요해요. 하나를 설치한 뒤 같은 명령을 다시 붙여 넣어 주세요."
  if [ "$(uname -s)" = "Darwin" ]; then
    say "  - Homebrew가 있으면: brew install python@3.12"
    say "  - 없으면: https://www.python.org/downloads/macos/ 에서 macOS 설치 파일(.pkg)"
  else
    say "  - 예: sudo apt install python3.12"
  fi
  exit 1
fi

say "에이전트를 받는 중이에요 ($REF)..."
mkdir -p "$HOME_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT INT TERM
curl -fsSL "$SRC" -o "$TMP/agent.tar.gz" || die "에이전트를 받지 못했어요: $SRC"
tar -xzf "$TMP/agent.tar.gz" -C "$TMP"
NEW="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
[ -f "$NEW/src/trace_agent/__main__.py" ] || die "받은 파일에 에이전트가 없어요: $SRC"
rm -rf "$HOME_DIR/src"
mv "$NEW/src" "$HOME_DIR/src"

# 진단 JSON은 ~/.trace-agent에 남긴다(올리지 못했을 때 `trace-agent upload`로 다시 올릴 수 있게)
cd "$HOME_DIR"
export TRACE_API_URL="$API"
export PYTHONPATH="$HOME_DIR/src"
if [ -z "$CODE" ]; then
  set -- run
else
  set -- run --code "$CODE"
fi
# curl | sh로 돌면 표준 입력이 이 스크립트라 동의 질문(y/N)을 못 받는다. 터미널에서 직접 받는다
if (exec </dev/tty) 2>/dev/null; then
  exec "$PY" -m trace_agent "$@" </dev/tty
fi
exec "$PY" -m trace_agent "$@"
