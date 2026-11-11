# 변경 기록

이 레포의 버전별 변경을 적는다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따른다.
기능 PR은 `## [Unreleased]` 아래에 한 줄을 더하고, 릴리스 PR에서 `## [x.y.z] - 날짜`로 바꾼다(CONTRIBUTING.md 3번).
main에 버전이 적힌 CHANGELOG가 올라가면 release.yml이 태그와 GitHub Release를 만든다.

## [Unreleased]

## [0.2.0] - 2026-11-11

**목표: 대회(11/13 코드 프리즈) 시연용 진단 에이전트 고정**
한 줄 설치(`gakdo.site/agent.sh`·`agent.ps1`)가 이 태그를 받으므로, 시연 날 설치되는 코드가 이 버전으로 고정된다.

### 추가
- 사용자용 읽기 전용 MCP 서버 `trace-mcp` (#13)
- 충전기가 없으면 벤치마크 전에 꽂을지 묻기 (#12)
- macOS에 smartctl이 없으면 받아서 SSD 수명 읽기 (#11)
- 맥에 파이썬 3.11 이상이 없으면 독립 실행형 파이썬 3.12를 받아 쓰기 (#10)
- 페어링 코드를 넣은 한 줄 설치·실행 스크립트 `agent.sh`·`agent.ps1` (#8, #9)

### 바꿈
- 한 줄 설치 스크립트가 기본으로 `develop` 대신 태그 `v0.2.0`을 받음(`TRACE_AGENT_REF`로 바꿀 수 있음)

### 추가
- 잠금·디스크 상태 올리기(contracts 11/7 추가): 진단 JSON에 `checks`{activationLock, diskEncryption, osDiskHealth}를 ON·OFF·OK·WARNING 코드로 실음. 못 읽으면 null
- 반납 점검 경고(요약): macOS 활성화 잠금·FileVault·OS SMART 상태, Windows BitLocker
- `trace-agent upload --code`: 올리지 못하고 남긴 JSON을 같은 Idempotency-Key로 다시 올림
- 페어링 교환 429면 Retry-After만큼 기다려 두 번까지 다시 시도, 교환 응답의 기기 시리얼이 다르면 올리지 않고 알림
- Windows: RAM 모듈 시리얼·부품 번호, 배터리 리포트의 배터리 시리얼(부품 교체 플래그용)

### 바뀜
- macOS: 외부 모니터는 부품에서 뺌(부품 변경 오탐 방지), https가 아닌 주소면 경고
- 벤치마크 안정화: 디스크는 캐시를 끈 핸들로 쓰고 읽음(macOS F_FULLFSYNC, Windows NO_BUFFERING·WRITE_THROUGH), 메모리 복사는 미리 잡은 버퍼에
- Windows: smartctl이 없으면 Get-StorageReliabilityCounter로 SSD 사용률·가동 시간
- Windows 진단 수집기(AG2): PowerShell CIM·root/wmi 배터리 mWh·smartctl, 디스크 읽기 캐시 우회
- 블로그(AIGJ-01-002-blog/devlog) CI/CD를 옮겨 초기 구성
