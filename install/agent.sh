#!/bin/sh
# TRACE 진단 에이전트 한 줄 설치·실행 (macOS. 수집기가 macOS용이라 Linux는 받기·실행만 된다)
#
#   curl -fsSL https://gakdo.site/agent.sh | sh -s 123456
#
# 파이썬 3.11 이상이 없으면 python-build-standalone 3.12를 ~/.trace-agent/python에 받아 쓴다(관리자 권한 필요 없음).
# 하는 일: 에이전트 소스를 GitHub에서 받아 ~/.trace-agent에 풀고(실행 의존성 jsonschema는 pip --target으로 ~/.trace-agent/lib에, pypi.org가 막히면 카카오 미러),
# TRACE_API_URL을 채워 `python3 -m trace_agent run --code <코드>`를 실행한다.
# 결과를 화면에 보여 주고 y를 넣어야 올린다. 비밀값은 이 파일에 없다(페어링 코드는 5분짜리 일회용).
#
# 바꿀 수 있는 값(환경 변수): TRACE_API_URL(기본 https://gakdo.site), TRACE_AGENT_REF(브랜치나 태그, 기본 develop),
# TRACE_AGENT_HOME(기본 ~/.trace-agent), TRACE_AGENT_SRC(소스 tar.gz 주소), TRACE_AGENT_PYTHON_URL(받을 파이썬 tar.gz)
set -eu

CODE="${1:-}"
API="${TRACE_API_URL:-https://gakdo.site}"
REF="${TRACE_AGENT_REF:-develop}"
HOME_DIR="${TRACE_AGENT_HOME:-$HOME/.trace-agent}"
SRC="${TRACE_AGENT_SRC:-https://codeload.github.com/GAKDO/agent/tar.gz/$REF}"

say() { printf '%s\n' "$*"; }
die() { printf '%s\n' "$*" >&2; exit 1; }

case "$CODE" in
  "") ;;
  [0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) die "페어링 코드는 6자리 숫자예요. 예: curl -fsSL https://gakdo.site/agent.sh | sh -s 123456" ;;
esac

# 파이썬 3.11 이상 찾기(macOS 기본 /usr/bin/python3는 3.9라 안 된다). 전에 받아 둔 파이썬을 먼저 쓴다
PY=""
for c in "$HOME_DIR/python/bin/python3" python3.13 python3.12 python3.11 python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
    PY="$c"
    break
  fi
done

# 없으면 독립 실행형 CPython(python-build-standalone, GitHub 릴리스)을 ~/.trace-agent/python에 푼다.
# 관리자 권한·설치 없이 이 폴더에만 두고, 받은 파일은 SHA-256으로 확인한다
PBS_BASE="https://github.com/astral-sh/python-build-standalone/releases/download/20241016"
PBS_VER="3.12.7+20241016"
sha256() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1"; else sha256sum "$1"; fi | cut -d' ' -f1; }
if [ -z "$PY" ]; then
  case "$(uname -s)-$(uname -m)" in
    Darwin-arm64) PBS_ARCH=aarch64-apple-darwin; PBS_SHA=4c18852bf9c1a11b56f21bcf0df1946f7e98ee43e9e4c0c5374b2b3765cf9508 ;;
    Darwin-x86_64) PBS_ARCH=x86_64-apple-darwin; PBS_SHA=60c5271e7edc3c2ab47440b7abf4ed50fbc693880b474f74f05768f5b657045a ;;
    Linux-x86_64) PBS_ARCH=x86_64-unknown-linux-gnu; PBS_SHA=43576f7db1033dd57b900307f09c2e86f371152ac8a2607133afa51cbfc36064 ;;
    Linux-aarch64) PBS_ARCH=aarch64-unknown-linux-gnu; PBS_SHA=bba3c6be6153f715f2941da34f3a6a69c2d0035c9c5396bc5bb68c6d2bd1065a ;;
    *) die "이 컴퓨터($(uname -s) $(uname -m))에 맞는 파이썬을 받을 수 없어요. 파이썬 3.11 이상을 설치한 뒤 다시 실행해 주세요." ;;
  esac
  PBS_URL="${TRACE_AGENT_PYTHON_URL:-$PBS_BASE/cpython-$PBS_VER-$PBS_ARCH-install_only.tar.gz}"
  say "파이썬 3.11 이상이 없어 파이썬 3.12를 받아요(설치 없이 $HOME_DIR/python 에만 풀어요)..."
  mkdir -p "$HOME_DIR"
  PTMP="$(mktemp -d)"
  curl -fsSL "$PBS_URL" -o "$PTMP/python.tar.gz" || { rm -rf "$PTMP"; die "파이썬을 받지 못했어요: $PBS_URL"; }
  if [ -z "${TRACE_AGENT_PYTHON_URL:-}" ] && [ "$(sha256 "$PTMP/python.tar.gz")" != "$PBS_SHA" ]; then
    rm -rf "$PTMP"
    die "받은 파이썬의 SHA-256이 맞지 않아 쓰지 않아요: $PBS_URL"
  fi
  rm -rf "$HOME_DIR/python"
  tar -xzf "$PTMP/python.tar.gz" -C "$HOME_DIR"   # python/ 폴더 하나가 풀린다
  rm -rf "$PTMP"
  PY="$HOME_DIR/python/bin/python3"
  "$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || die "받은 파이썬을 실행하지 못했어요: $PY"
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

# 실행 의존성(pyproject.toml의 dependencies, 지금은 jsonschema)을 ~/.trace-agent/lib에 받는다. 이미 있으면 건너뛴다.
# 학교 망은 pypi.org를 막으므로 안 되면 카카오 미러로 다시 받는다
LIB="$HOME_DIR/lib"
DEPS="$("$PY" -c 'import sys, tomllib; print(" ".join(tomllib.load(open(sys.argv[1], "rb"))["project"]["dependencies"]))' "$NEW/pyproject.toml")"
if [ -n "$DEPS" ] && ! PYTHONPATH="$LIB" "$PY" -c 'import jsonschema, referencing' 2>/dev/null; then
  "$PY" -m pip --version >/dev/null 2>&1 || die "이 파이썬($PY)에 pip가 없어요. python.org 설치 파일이나 brew install python@3.12로 설치한 파이썬을 써 주세요."
  say "필요한 패키지를 받는 중이에요: $DEPS"
  rm -rf "$LIB"
  # shellcheck disable=SC2086 # DEPS는 공백으로 나눈 패키지 목록
  if ! "$PY" -m pip install -q --disable-pip-version-check --timeout 10 --retries 1 --target "$LIB" $DEPS 2>/dev/null; then
    say "pypi.org에 닿지 않아 카카오 미러로 다시 받아요..."
    rm -rf "$LIB"
    # shellcheck disable=SC2086
    "$PY" -m pip install -q --disable-pip-version-check --target "$LIB" -i https://mirror.kakao.com/pypi/simple $DEPS \
      || die "패키지를 받지 못했어요: $DEPS"
  fi
fi

# 진단 JSON은 ~/.trace-agent에 남긴다(올리지 못했을 때 `trace-agent upload`로 다시 올릴 수 있게)
cd "$HOME_DIR"
export TRACE_API_URL="$API"
export PYTHONPATH="$HOME_DIR/src:$LIB"
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
