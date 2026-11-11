# macOS 명령 출력 고정 파일

2026-11-02 팀 MacBook Air(M2, Mac14,2, macOS 26.5, arm64)에서 읽기 전용으로 받은 실제 출력이다.

- 익명화: 기기 시리얼 → `C02TEST00001`, SSD 시리얼 → `SSDTEST01`, 배터리 시리얼 → `BATTEST01`, 디스플레이 시리얼 → `DISPTEST01`, platform_UUID·provisioning_UDID → 0으로 채운 UUID
- 줄인 것: `power.json`의 예약 wake 이벤트 항목, `ioreg_battery.plist`는 수백 개 키 중 에이전트가 읽는 키와 그 주변만 남김(값은 원본 그대로)
- 그 시각 상태: 배터리 전원(충전기 없음), 잔량 59%, 발열 경고 없음, 프로세스 745개
- 이 맥에는 smartctl이 설치돼 있지 않았다(→ SSD는 `SKIPPED`·`TOOL_ERROR`). smartctl 출력은 설치 뒤 받아 더한다
