# 구현 계획: AG1 macOS 진단 에이전트

**브랜치**: `claude/project-thread-sy1p9l` | **작성일**: 2026-11-02 | **명세**: [spec.md](spec.md)

## 요약

`trace-agent` 명령줄 도구를 만든다. 고정 목록의 macOS 명령(system_profiler·ioreg·pmset·smartctl·ps·sysctl)만 실행해 출력을 읽고, contracts 진단 JSON(diag.v1)을 만든 뒤 스키마로 검증한다. 요약을 보여 주고 동의하면 페어링 코드를 AGENT JWT로 바꿔 diagnostics-server에 올린다. 전원이 있을 때만 자체 벤치마크 5종을 3회씩 돌린다.

## 기술 맥락

- **언어**: Python 3.12(3.11 이상), 표준 라이브러리 우선(`subprocess`, `json`, `plistlib`, `urllib.request`, `platform`, `multiprocessing`)
- **의존성**: `jsonschema`(+ `referencing`) 하나. contracts 스키마 검증에만 쓴다
- **스키마**: contracts `diagnostics/result.schema.json`과 `schemas/codes.gen.schema.json`을 `src/trace_agent/schema/`에 그대로 복사해 넣고(contracts develop `de2ff0e`, codes.yaml 0.4.0), 같은 상대 경로로 `$ref`를 푼다. 값을 손으로 옮기지 않는다
- **테스트**: pytest + 실제 맥에서 받은 명령 출력 고정 파일(`tests/fixtures/macos/`, 시리얼·UUID·이름은 가짜로 바꿈). 명령 실행은 함수 하나(`run`)로 감싸 테스트에서 바꿔 끼운다. 네트워크는 `http_post` 하나로 감싼다
- **설정**: `TRACE_API_URL`(gateway). 토큰은 메모리에만, 출력하지 않음

## 헌법 점검

| 원칙 | 점검 | 결과 |
| --- | --- | --- |
| I. 계약 | 결과는 contracts diag.v1 스키마를 복사본 그대로 써서 검증. 코드 값은 생성 스키마에서만. 계약 변경 없음 | 통과 |
| II. 경계 | 에이전트는 auth-server(페어링 교환)와 diagnostics-server(업로드)에 gateway로만 닿음 | 통과 |
| III. 기록 | 못 읽은 값은 null + 사유, 0을 모름으로 쓰지 않음. 올리지 못하면 JSON을 파일로 남김 | 통과 |
| IV. 테스트 | 수용 시나리오 문장을 테스트 이름으로, 실제 출력 고정 파일 | 통과 |
| V. 비밀·개인정보 | 명령 고정 목록, 컴퓨터 이름·UUID 버림, 토큰 출력 안 함 | 통과 |
| VI. 단순 | 터미널 도구 하나, GUI·설치 파일 없음 | 통과 |

## 구조

```text
src/trace_agent/
├── __main__.py        # trace-agent collect | run --code
├── commands.py        # 고정 명령 목록 ALLOWED, run() — 목록 밖은 거절
├── macos.py           # 출력 → 기기·부품·배터리·SSD·조건 (파서는 순수 함수)
├── benchmark.py       # 5종 × 3회, 중앙값 (PR 2)
├── report.py          # 진단 JSON 조립·스키마 검증·요약 문장
├── upload.py          # 페어링 교환·업로드 (PR 2)
└── schema/            # contracts 복사본
    ├── diagnostics/result.schema.json
    └── schemas/codes.gen.schema.json
tests/
├── fixtures/macos/    # 실제 맥 출력(익명화)
├── test_macos.py
├── test_report.py
├── test_benchmark.py  # PR 2
└── test_upload.py     # PR 2
```

## 읽는 명령 (고정 목록)

| 명령 | 읽는 값 |
| --- | --- |
| `system_profiler SPHardwareDataType -json` | 시리얼·모델 식별자·모델 이름·칩·코어·메모리 |
| `system_profiler SPPowerDataType -json` | 사이클·최대 용량 %·OS 판정·충전기 연결 |
| `system_profiler SPNVMeDataType -json` | SSD 모델·용량·시리얼 |
| `system_profiler SPDisplaysDataType -json` | 디스플레이 이름·해상도 |
| `ioreg -r -a -c AppleSmartBattery` | 설계·완충 용량(mAh), 배터리 모델·시리얼 (plist) |
| `pmset -g batt` | 전원·잔량 |
| `pmset -g therm` | 발열 경고 |
| `smartctl -j -a disk0` | NVMe 건강 로그 |
| `ps -A -o pid=` | 프로세스 수(개수만) |
| `sysctl -n kern.boottime` | 가동 시간 |

OS 버전·아키텍처는 `platform.mac_ver()`·`platform.machine()`(명령 실행 없음).

## 조사 메모 (11/2 실제 맥 출력)

- 완충 용량은 ioreg `NominalChargeCapacity`(없으면 `AppleRawMaxCapacity`)를 쓴다. 팀 맥북에서 4070 ÷ 4563 = 89%로 OS 최대 용량 90%에 가깝고, `AppleRawMaxCapacity`(3943, 86%)는 온도에 따라 흔들린다. OS %는 `osMaxCapacityPercent`로 따로 보낸다
- 충전기 연결은 `pmset -g batt` 첫 줄('AC Power'·'Battery Power')로 본다. `system_profiler SPPowerDataType`의 `sppower_battery_charger_connected`와 같다
- smartctl은 기본 설치돼 있지 않다 → 운영 안내에 `brew install smartmontools`를 넣는다

## PR 나누기

- PR 1: commands·macos·report(수집·조립·검증·요약), 실제 맥 출력 고정 파일 — 스토리 1
- PR 2: benchmark·upload·`trace-agent collect`·`trace-agent run --code` — 스토리 2·3

## 복잡도 기록

헌법 위반 없음.
