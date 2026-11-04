# Windows 명령 출력 고정 파일

**만든 출력이다(실기 출력이 아님).** 2026-11-04 LG 그램(16Z90R, Windows 11)을 가정해 PowerShell 5.1 `ConvertTo-Json`과
smartctl 7.4 `-j`의 형식대로 손으로 썼다. 실제 그램에서 `trace-agent run`을 돌린 뒤 같은 명령의 출력으로 바꾼다.

- 익명화 규칙은 macOS 고정 파일과 같다: 기기 시리얼 `LGTEST00001`, SSD `SSDTEST01`, 배터리 `BATTEST01`
- `disks.json`에 USB 메모리 한 개, `video.json`에 화면이 없는 원격 어댑터 한 개를 일부러 넣었다(둘 다 부품에서 빠져야 함)
- 그 시각 상태: 전원 연결, 잔량 72%, 프로세스 231개, 부팅 3시간 30분 뒤, 관리자 권한으로 smartctl 실행
