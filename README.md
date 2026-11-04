# agent

TRACE(노트북 렌탈 상태 기록 서비스)의 **agent**: 진단 에이전트: 렌탈 노트북의 부품·배터리·SSD·벤치마크를 읽어 동의 후 올린다 (macOS·Windows)

- 담당: B
- 설계: [GAKDO/docs](https://github.com/GAKDO/docs) — 진단 JSON v0(design/diagnostics-json-v0.md)
- 기술: Python 3.12

## 실행 (macOS)

```bash
python -m pip install -e .
brew install smartmontools        # SSD 수명 값(없으면 SSD는 "생략, TOOL_ERROR"로 남음)
export TRACE_API_URL=https://<gateway 주소>
trace-agent run                    # 진단만 하고 결과를 보여 주고 trace-diagnostics.json에 남김
trace-agent run --code 482913      # 관리자 화면의 페어링 코드: 결과를 본 뒤 y를 넣어야 올림
```

- 전원 어댑터를 꽂아야 벤치마크(약 1분)를 돌린다. 꽂지 않으면 벤치마크 없이 사유(NO_AC_POWER)만 남는다.
- 읽는 명령은 `src/trace_agent/commands.py`의 `ALLOWED` 목록뿐이다. 사용자 파일·브라우저 기록은 읽지 않고, 컴퓨터 이름·플랫폼 UUID는 보내지 않는다.
- 결과 형식은 contracts 진단 JSON(diag.v1)이고, 올리기 전에 `src/trace_agent/schema/`의 복사본으로 검증한다.

## 실행 (Windows)

PowerShell을 **관리자 권한으로** 열어야 SSD 수명 값을 읽는다(아니면 SSD는 "생략, NO_PERMISSION").

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
