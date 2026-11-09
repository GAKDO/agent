# agent

TRACE(노트북 렌탈 상태 기록 서비스)의 **agent**: 진단 에이전트: 렌탈 노트북의 부품·배터리·SSD·벤치마크를 읽어 동의 후 올린다 (macOS·Windows)

- 담당: B
- 설계: [GAKDO/docs](https://github.com/GAKDO/docs) — 진단 JSON v0(design/diagnostics-json-v0.md)
- 기술: Python 3.12

## 한 줄로 설치·실행 (관리자 화면의 페어링 코드)

관리자 화면 렌탈 상세의 "명령 복사"(web #100)로 받은 명령을 붙여 넣으면, 에이전트 소스를 받아 풀고 `TRACE_API_URL=https://gakdo.site`로 바로 실행한다. 실행 의존성(jsonschema)은 `pip --target`으로 같은 폴더의 `lib`에 받고, pypi.org가 막힌 학교 망에서는 카카오 미러로 다시 받는다. 결과를 보여 준 뒤 `y`를 넣어야 올린다.

```bash
# macOS (파이썬 3.11 이상이 없으면 독립 실행형 파이썬 3.12를 ~/.trace-agent/python에, smartctl이 없으면 smartmontools 7.4 dmg에서 꺼낸 smartctl을 ~/.trace-agent/bin에 받아 쓴다. 관리자 권한 필요 없음)
curl -fsSL https://gakdo.site/agent.sh | sh -s 123456
```

smartctl을 받지 않으려면 `curl -fsSL https://gakdo.site/agent.sh | TRACE_AGENT_NO_SMARTCTL=1 sh -s 123456`처럼 `sh` 앞에 붙인다(SSD만 "읽지 못함"으로 남는다).

```powershell
# Windows PowerShell (관리자 권한이면 SSD 수명까지 읽는다. 파이썬이 없으면 nuget.org zip을 받아 쓴다)
& ([scriptblock]::Create((irm https://gakdo.site/agent.ps1))) 123456
```

- 스크립트: `install/agent.sh`, `install/agent.ps1`. 소스는 `~/.trace-agent`(Windows는 `%LOCALAPPDATA%\trace-agent`)에 풀리고 진단 JSON도 거기 남는다
- `/agent.sh`·`/agent.ps1`은 web nginx가 `raw.githubusercontent.com/GAKDO/agent/develop/install/...`로 302 넘긴다
- 다른 서버로 올릴 때: `curl -fsSL <화면>/agent.sh | TRACE_API_URL=<API 주소> sh -s 123456`(변수는 `sh` 쪽에 붙인다)
- 환경 변수: `TRACE_API_URL`, `TRACE_AGENT_REF`(받을 브랜치나 태그, 기본 develop. 프리즈 때 태그로 고정 예정), `TRACE_AGENT_HOME`, `TRACE_AGENT_SRC`, `TRACE_AGENT_PYTHON_URL`

## 실행 (macOS)

```bash
python -m pip install -e .
brew install smartmontools        # SSD 수명 값(없으면 SSD는 "생략, TOOL_ERROR"로 남음)
export TRACE_API_URL=https://<gateway 주소>
trace-agent run                    # 진단만 하고 결과를 보여 주고 trace-diagnostics.json에 남김
trace-agent run --code 482913      # 관리자 화면의 페어링 코드: 결과를 본 뒤 y를 넣어야 올림
trace-agent upload --code 123456   # 올리지 못했을 때: 남긴 JSON을 새 코드로 다시 올림(같은 Idempotency-Key)
```

- 요약 끝의 `잠금`·`[주의]` 줄은 반납·출고 때 직원이 바로 볼 경고다. 활성화 잠금(나의 Mac 찾기)·FileVault·BitLocker가 켜져 있으면 초기화 전에 고객에게 해제를 요청한다. 같은 상태가 진단 JSON `checks`(ON·OFF·OK·WARNING 코드, contracts 11/7 추가)로 함께 올라가고, diagnostics-server가 켜짐·경고에 점검 플래그를 붙인다

- 전원 어댑터를 꽂아야 벤치마크(약 1분)를 돌린다. 꽂지 않았으면 벤치마크 전에 묻는다: 충전기를 꽂고 Enter를 누르면 다시 확인해 돌리고, `n`이면(또는 세 번 확인해도 없으면) 벤치마크 없이 사유(NO_AC_POWER)만 남긴다.
- 읽는 명령은 `src/trace_agent/commands.py`의 `ALLOWED` 목록뿐이다. 사용자 파일·브라우저 기록은 읽지 않고, 컴퓨터 이름·플랫폼 UUID는 보내지 않는다.
- 결과 형식은 contracts 진단 JSON(diag.v1)이고, 올리기 전에 `src/trace_agent/schema/`의 복사본으로 검증한다.

## 실행 (Windows)

PowerShell을 **관리자 권한으로** 열어야 SSD 수명 값을 읽는다(아니면 SSD는 "생략, NO_PERMISSION").
smartmontools가 없으면 Windows 기본 기능(`Get-StorageReliabilityCounter`, 관리자 권한)으로 사용률(Wear)·가동 시간만 읽는다(예비·경고·미디어 오류는 null). 가동 시간을 못 주는 드라이버는 Wear도 0으로 채우므로(갤럭시 북 실측: smartctl 4%, Wear 0) 그때는 SSD를 "읽지 못함(UNSUPPORTED)"으로 둔다. 정확한 값은 smartmontools를 설치해서 읽는다.

```powershell
winget install Python.Python.3.12 Git.Git GitHub.cli smartmontools.smartmontools
# 설치 뒤 PowerShell 창을 새로 연다
gh auth login
gh repo clone GAKDO/agent -- -b develop; cd agent
py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1   # 막히면 Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
python -m pip install -e .
trace-agent run
```

- 스마트 앱 컨트롤 같은 앱 제어가 켜져 있으면 서명 없는 `pip.exe`·`trace-agent.exe`가 막힌다. 그때는 `.\.venv\Scripts\python.exe -m pip install -e .`, `.\.venv\Scripts\python.exe -m trace_agent run`으로 부른다(Activate도 필요 없음)
- 학교 망처럼 pypi.org·python.org가 막히면 파이썬은 `https://www.nuget.org/api/v2/package/python/3.12.10`(zip, `tools\python.exe`), 패키지는 `pip install -i https://mirror.kakao.com/pypi/simple -e .`로 받는다
- 읽는 값: `Get-CimInstance`(기기·CPU·RAM·화면·배터리), `Get-PhysicalDisk`(SSD), `root/wmi`(배터리 설계·완충 mWh, 사이클. 못 읽으면 `powercfg /batteryreport` XML), smartctl(SSD 수명). 명령 전체는 `commands.py`의 `WINDOWS`
- 발열 상태·OS 배터리 판정·최대 용량 %는 Windows에서 읽지 않아 null이다(계약대로)

## 테스트

```bash
python -m ruff check . && python -m pytest
```

## CI

| 워크플로 | 언제 | 하는 일 |
|---|---|---|
| `python-ci` | PR, develop·main push | ruff + pytest (ubuntu·macos·windows) |
| `비밀값 검사`·`release`·알림 | | 다른 레포와 같음 |
