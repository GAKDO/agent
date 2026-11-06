# 변경 기록

이 레포의 버전별 변경을 적는다. 형식은 [Keep a Changelog](https://keepachangelog.com/ko/1.1.0/)를 따른다.
기능 PR은 `## [Unreleased]` 아래에 한 줄을 더하고, 릴리스 PR에서 `## [x.y.z] - 날짜`로 바꾼다(CONTRIBUTING.md 3번).
main에 버전이 적힌 CHANGELOG가 올라가면 release.yml이 태그와 GitHub Release를 만든다.

## [Unreleased]

### 추가
- 반납 점검 경고(올리지 않고 요약에만): macOS 활성화 잠금·FileVault·OS SMART 상태, Windows BitLocker
- `trace-agent upload --code`: 올리지 못하고 남긴 JSON을 같은 Idempotency-Key로 다시 올림
- 페어링 교환 429면 Retry-After만큼 기다려 두 번까지 다시 시도, 교환 응답의 기기 시리얼이 다르면 올리지 않고 알림
- Windows: RAM 모듈 시리얼·부품 번호, 배터리 리포트의 배터리 시리얼(부품 교체 플래그용)

### 바뀜
- macOS: 외부 모니터는 부품에서 뺌(부품 변경 오탐 방지), https가 아닌 주소면 경고
- 벤치마크 안정화: 디스크는 캐시를 끈 핸들로 쓰고 읽음(macOS F_FULLFSYNC, Windows NO_BUFFERING·WRITE_THROUGH), 메모리 복사는 미리 잡은 버퍼에
- Windows: smartctl이 없으면 Get-StorageReliabilityCounter로 SSD 사용률·가동 시간
- Windows 진단 수집기(AG2): PowerShell CIM·root/wmi 배터리 mWh·smartctl, 디스크 읽기 캐시 우회
- 블로그(AIGJ-01-002-blog/devlog) CI/CD를 옮겨 초기 구성
