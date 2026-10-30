# agent

TRACE(노트북 렌탈 상태 기록 서비스)의 **agent**: 진단 에이전트: 렌탈 노트북의 부품·배터리·SSD·벤치마크를 읽어 동의 후 올린다 (macOS·Windows)

- 담당: B
- 설계: [GAKDO/docs](https://github.com/GAKDO/docs) — 진단 JSON v0(design/diagnostics-json-v0.md)
- 기술: Python 3.12

## 실행

```bash
python -m pip install -e ".[dev]"
```

```bash
python -m trace_agent
```

## 테스트

```bash
python -m ruff check . && python -m pytest
```

## CI

| 워크플로 | 언제 | 하는 일 |
|---|---|---|
| `python-ci` | PR, develop·main push | ruff + pytest (ubuntu·macos·windows) |
| `비밀값 검사`·`release`·알림 | | 다른 레포와 같음 |
