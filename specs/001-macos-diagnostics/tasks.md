# 작업: AG1 macOS 진단 에이전트

**PR 나누기**: PR 1 = Phase 1~3의 수집·검증(T001~T009, 명령줄 없음), PR 2 = T010과 Phase 4~5(벤치마크·동의·업로드·명령줄). 명령줄은 벤치마크가 있어야 전원 연결 상태의 결과가 스키마를 통과하므로 PR 2로 옮김

## Phase 1: 준비

- [x] T001 `pyproject.toml`: `jsonschema>=4.18`, 스키마 파일 패키지 데이터
- [x] T002 [P] `src/trace_agent/schema/`: contracts `de2ff0e`의 result.schema.json·codes.gen.schema.json 복사
- [x] T003 [P] `tests/fixtures/macos/`: 실제 맥 명령 출력(시리얼·UUID·이름 익명화)

## Phase 2: 기반

- [x] T004 `src/trace_agent/commands.py`: 고정 목록 `ALLOWED`, `run(argv)`(목록 밖 거절, 타임아웃, 없는 명령은 결과에 표시)
- [x] T005 [P] `tests/test_commands.py`: 목록 밖 명령 거절, 목록에 사용자 폴더·브라우저 경로 없음

## Phase 3: 스토리 1 - 진단 결과를 보고 확인한다 🎯 MVP

- [x] T006 [P] [US1] `tests/test_macos.py`: 배터리 값이 OS 값과 같다, 사이클 0은 null, smartctl 실패는 SKIPPED+사유, 배터리 없으면 NO_BATTERY
- [x] T007 [P] [US1] `tests/test_report.py`: 스키마 통과, 컴퓨터 이름·UUID가 JSON에 없다, 요약에 sources
- [x] T008 [US1] `src/trace_agent/macos.py`: 파서(순수 함수)와 `collect(run)`
- [x] T009 [US1] `src/trace_agent/report.py`: 조립·검증·요약
- [ ] T010 [US1] `src/trace_agent/__main__.py`: `trace-agent collect [--out 파일]` (PR 2)

## Phase 4: 스토리 2 - 전원이 있을 때만 벤치마크 (PR 2)

- [ ] T011 [P] [US2] `tests/test_benchmark.py`: 전원 없으면 실행 0회 + NO_AC_POWER, 있으면 5종 × 3회 + 가운데 값
- [ ] T012 [US2] `src/trace_agent/benchmark.py`

## Phase 5: 스토리 3 - 동의한 뒤에만 올린다 (PR 2)

- [ ] T013 [P] [US3] `tests/test_upload.py`: y 아니면 요청 0회, y면 교환 → 업로드(Idempotency-Key, consentedAt), 422·409는 code 표시·파일 남김
- [ ] T014 [US3] `src/trace_agent/upload.py`, `trace-agent run --code`

## Phase 6: 마무리

- [ ] T015 `README.md`: 설치·실행·읽는 명령 목록
- [ ] T016 팀 노트북 3대에서 실행, DI1 뒤 저장 확인
