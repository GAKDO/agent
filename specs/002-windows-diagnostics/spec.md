# 기능 명세: AG2 Windows 진단 에이전트

**기능 브랜치**: `feature/002-windows-diagnostics`

**작성일**: 2026-11-04

**상태**: 초안 (LG 그램 실기 확인 전)

**입력**: 백로그 AG2 설명: "AG1과 같은 진단을 Windows에서 한다(FR-DIA-01~05, NFR-02). 배터리 용량은 mWh로 보내고 환산하지 않는다. SSD SMART는 관리자 권한이 없으면 생략 사유를 남긴다. 수용 기준은 AG1과 같고, LG 그램에서 확인한다."

**요구사항 ID**: FR-DIA-01, FR-DIA-02, FR-DIA-03, FR-DIA-04, FR-DIA-05, NFR-02

## 명확화

### 세션 2026-11-04

- Q: 무엇으로 읽나요? → A: PowerShell 5.1(`powershell`, Windows에 늘 있음)의 `Get-CimInstance`·`Get-PhysicalDisk`를 고른 속성만 `Select-Object`해 `ConvertTo-Json`으로 받는다. `powercfg /batteryreport`는 파일 경로를 받아야 해서 쓰지 않고, 같은 값(설계·완충 mWh, 사이클)을 `root/wmi`의 `BatteryStaticData`·`BatteryFullChargedCapacity`·`BatteryCycleCount`에서 읽는다
- Q: 컴퓨터 이름은? → A: `Win32_ComputerSystem`에서 Manufacturer·Model·SystemFamily만 고른다. Name·UserName·UUID는 처음부터 꺼내지 않는다
- Q: SSD 수명 값은? → A: `smartctl -j -a /dev/sda`(PATH에 없으면 `C:\Program Files\smartmontools\bin\smartctl.exe`). 관리자 권한이 없으면 `SKIPPED`·`NO_PERMISSION`, 둘 다 없으면 `TOOL_ERROR`
- Q: 발열·OS 판정·최대 용량 %는? → A: 계약대로 Windows는 null
- Q: 전원 연결은? → A: `root/wmi BatteryStatus.PowerOnline`. 못 읽으면 `Win32_Battery.BatteryStatus`(2·6~9 = 전원), 배터리가 없으면 연결로 본다
- Q: 디스크 읽기 벤치마크가 캐시 속도가 되지 않게 하려면? → A: 쓴 파일을 `FILE_FLAG_NO_BUFFERING`으로 다시 열어 읽는다(ctypes). 실패하면 보통 읽기로 잰다
- Q: 어느 수집기를 쓰나요? → A: `sys.platform == "win32"`면 Windows, 그 밖은 macOS

## 수용 시나리오

1. 그램 명령 출력으로 만든 진단이 diag.v1을 통과하고 `os.type`은 `WINDOWS`다.
2. 배터리 설계·완충 용량은 root/wmi의 mWh 값 그대로다(환산하지 않음). 사이클 0이나 못 읽은 값은 null이다.
3. 관리자 권한이 없으면 SSD는 `SKIPPED`·`NO_PERMISSION`이고 값은 모두 null이다.
4. 꽂아 둔 USB 메모리와 화면이 없는 원격 어댑터는 부품에 들어가지 않는다.
5. 실행하는 PowerShell 명령에 컴퓨터 이름·사용자 이름·UUID 속성이 없다.
6. 벤치마크·동의·업로드는 AG1과 같다(전원이 없으면 NO_AC_POWER, `--code` 없으면 올리지 않음).

## 범위 밖

- 설치 파일(.exe·PyInstaller), GUI
- `tests/fixtures/windows`는 형식대로 손으로 쓴 출력이다. LG 그램 실기 출력으로 바꾸는 것은 실기 확인 때 한다
