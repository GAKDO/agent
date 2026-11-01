# agent

TRACE의 진단 에이전트 (macOS·Windows) 레포입니다. 담당: B. 이 레포의 기능: AG1, AG2 (GAKDO/docs `speckit/backlog.md`).

## 먼저 읽을 것

- 헌법: `.specify/memory/constitution.md` (모든 명세·계획·구현의 기준. 원본은 GAKDO/docs `speckit/constitution.md`)
- 기능 목록과 붙여 넣을 설명: GAKDO/docs [`speckit/backlog.md`](https://github.com/GAKDO/docs/blob/main/speckit/backlog.md)
- 설계서: [`design/mvp-design.md`](https://github.com/GAKDO/docs/blob/main/design/mvp-design.md), REST API: [`design/rest-api-v0.md`](https://github.com/GAKDO/docs/blob/main/design/rest-api-v0.md), 테이블: [`design/ddl.md`](https://github.com/GAKDO/docs/blob/main/design/ddl.md), 결정: [`decisions.md`](https://github.com/GAKDO/docs/blob/main/decisions.md)
- 계약 원본: [GAKDO/contracts](https://github.com/GAKDO/contracts) (OpenAPI·JSON Schema·`codes.yaml`)

## 명령

- 설치: `python -m pip install -e ".[dev]"`
- 검사: `ruff check . && pytest -q`

## Spec Kit으로 기능 하나 만들기

1. `git switch develop && git pull`
2. `/speckit-specify` + backlog.md의 설명 → `feature/<번호>-<이름>` 브랜치와 `specs/<번호>-<이름>/spec.md`
3. `/speckit-clarify` → 질문에 답하기
4. `/speckit-plan` + 아래 "계획에 줄 기술 설명"
5. `/speckit-tasks` → `/speckit-analyze` → `/speckit-implement` → `/speckit-converge` (Converged까지 반복)
6. 로컬 검사가 통과하면 PR을 `develop`으로. 본문에 요구사항 ID를 적고 `specs/` 문서도 함께 올린다

## 계획에 줄 기술 설명

`/speckit-plan` 뒤에 그대로 붙여 넣습니다.

```
Python 3.12, 표준 라이브러리 우선. macOS는 system_profiler·ioreg·smartctl·pmset, Windows는 PowerShell(Get-CimInstance)·powercfg /batteryreport·smartctl의 출력을 읽는다. 읽는 명령·경로 목록을 코드 상수로 고정한다. 결과는 contracts의 진단 JSON Schema로 검증한 뒤 보여 주고, 동의하면 페어링 JWT로 올린다. 테스트는 pytest + 실제 기기에서 받은 명령 출력 고정 파일. ruff 통과.
```

## 꼭 지킬 것

- 계약(API·이벤트·진단 JSON·코드 값)을 바꿔야 하면 코드를 고치지 말고 멈추고 사람에게 알린다.
- 비밀번호·토큰·키·학번을 코드·문서·커밋에 넣지 않는다. 설정은 환경 변수로 받는다.
- 커밋은 `<종류>(<범위>): <내용>`(feat·fix·refactor·test·docs·chore·ci), 문서·PR·주석은 한국어.
- 레포 이름은 `_server`, 클러스터 안 서비스·이미지 이름은 `-server`(예: `auth-server`).
