"""명령줄 진입점.

    trace-agent                         버전
    trace-agent run                     진단하고 결과만 보여 주고 파일로 남긴다(올리지 않음)
    trace-agent run --code 482913       진단 → 결과 보기 → 동의하면 올린다
    trace-agent upload --code 482913    올리지 못하고 남긴 JSON을 다시 올린다(같은 Idempotency-Key)
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import re
import sys
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from . import __version__, benchmark, commands, macos, report, upload, windows


def _key_file(out: Path) -> Path:
    return out.with_name(out.name + ".key")


def _write_atomic(path: Path, text: str) -> None:
    """임시 파일에 다 쓴 뒤 바꿔 끼운다. 쓰다 실패해도 원래 파일은 그대로 남는다."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _save(doc: dict[str, Any], out: Path, idempotency_key: str | None = None) -> None:
    _write_atomic(out, json.dumps(doc, ensure_ascii=False, indent=2))
    if idempotency_key:
        # 다시 올릴 때 같은 키를 써야, 사실은 저장됐는데 응답만 못 받은 경우에도 409 대신 처음 응답을 받는다
        _write_atomic(_key_file(out), idempotency_key)
    else:
        # 키 없이 새로 남긴 진단에 지난 진단의 키가 붙어 엉뚱한 응답을 받지 않게 지운다
        _key_file(out).unlink(missing_ok=True)
    print(f"진단 JSON을 {out}에 남겼어요.")


def _target(api: str) -> str:
    """동의 질문 바로 위에 보일 전송 대상. 평문이면 그 자리에서 다시 알린다."""
    if api.lower().startswith("https://"):
        how = "암호화(https)"
    elif upload.insecure(api):
        how = "암호화되지 않음, 토큰과 시리얼이 그대로 나가요"
    else:
        how = "암호화되지 않음, 이 컴퓨터 안에서만 오가요"  # localhost 시험
    return f"보낼 곳: {api} ({how})"


def _check_api(api: str, code: str | None) -> int | None:
    """코드·주소를 확인한다. 문제가 있으면 끝낼 코드, 없으면 None."""
    if code is None:
        return None
    if not re.fullmatch(r"\d{6}", code):
        print("페어링 코드는 6자리 숫자예요.", file=sys.stderr)
        return 2
    if not api:
        print("환경 변수가 없음: TRACE_API_URL", file=sys.stderr)
        return 2
    if upload.insecure(api):
        print("주의: TRACE_API_URL이 https가 아니라 토큰이 암호화되지 않고 나가요.", file=sys.stderr)
    return None


def _upload(api: str, code: str, doc: dict[str, Any], out: Path, post: upload.Post, sleep: upload.Sleep,
            idempotency_key: str) -> int:
    """교환 → 시리얼 대조 → 업로드. 실패하면 JSON과 키를 남겨 `trace-agent upload`로 다시 올릴 수 있게 한다."""
    try:
        pairing = upload.exchange(api, code, post, sleep, notify=lambda m: print(m, flush=True))
        serial = doc["device"]["serial"]
        if pairing.device_serial and pairing.device_serial != serial:
            # 서버도 422로 막지만, 기기를 잘못 고른 것을 바로 알려 준다(시리얼 전체는 화면에 남기지 않음)
            print(f"이 노트북(시리얼 끝 {serial[-4:]})은 페어링 코드의 기기(끝 {pairing.device_serial[-4:]})가 "
                  "아니에요. 관리자 화면에서 이 기기의 렌탈로 코드를 다시 만들어 주세요.", file=sys.stderr)
            _save(doc, out, idempotency_key)
            return 1
        result = upload.send(api, pairing.token, doc, post, idempotency_key)
    except upload.UploadError as err:
        print(f"올리지 못했어요: {err}", file=sys.stderr)
        _save(doc, out, idempotency_key)
        print(f"새 페어링 코드를 받아 `trace-agent upload --file {out} --code <코드>`로 다시 올릴 수 있어요.",
              file=sys.stderr)
        return 1
    _key_file(out).unlink(missing_ok=True)
    print(f"올렸어요. 점검 플래그 {len(result.get('flags', []))}개")
    return 0


def _wait_for_power(collected: dict[str, Any], power: Callable[[], dict[str, Any]],
                    ask: Callable[[str], str]) -> None:
    """충전기가 없으면 벤치마크 전에 묻는다(11/9: 충전기를 깜박하고 돌려 벤치마크가 빠짐).

    Enter면 전원을 다시 읽고, n이면 충전기 없이 진행한다(벤치마크는 NO_AC_POWER로 건너뜀)."""
    print("\n충전기가 연결되어 있지 않아요. 배터리로는 성능 측정(벤치마크)을 하지 않아요.")
    for _ in range(3):  # 세 번 확인해도 안 되면 충전기 없이 진행
        try:
            answer = ask("충전기를 꽂고 Enter를 누르면 다시 확인해요. 충전기 없이 진행하려면 n: ").strip().lower()
        except EOFError:  # 터미널이 없으면 묻지 않고 전처럼 진행
            return
        if answer == "n":
            print("충전기 없이 진행해요. 벤치마크는 건너뛰어요.")
            return
        now = power()
        if now["acPower"]:
            collected["conditions"].update(now)
            print("충전기가 연결됐어요.")
            return
        print("아직 충전기가 확인되지 않아요.")
    print("충전기를 확인하지 못해 충전기 없이 진행해요. 벤치마크는 건너뛰어요.")


def _run(args: argparse.Namespace, env: Mapping[str, str], ask: Callable[[str], str], run: commands.Runner,
         post: upload.Post, workloads: Any, clock: Callable[[], str], sleep: upload.Sleep) -> int:
    api = env.get("TRACE_API_URL", "").rstrip("/")
    if (code := _check_api(api, args.code)) is not None:
        return code
    print("기기 정보를 읽는 중이에요...", flush=True)
    system = windows if args.system == "win32" else macos
    collected = system.collect(run)
    if not collected["conditions"]["acPower"]:
        _wait_for_power(collected, lambda: system.power(run), ask)
    if collected["conditions"]["acPower"]:
        print("벤치마크를 돌려요. 1분쯤 걸리니 전원을 연결한 채로 기다려 주세요.", flush=True)
    try:
        benches, skipped = benchmark.run(collected["conditions"]["acPower"], workloads,
                                         progress=lambda line: print("  " + line, flush=True))
    except (OSError, RuntimeError) as err:  # 디스크 부족(OSError)·프로세스 풀(BrokenProcessPool) 오류가 나도 이미 수집한 진단은 남긴다
        print(f"벤치마크를 끝내지 못해 건너뛰어요: {err}", file=sys.stderr)
        benches, skipped = [], "TOOL_ERROR"
    collected_at = clock()
    doc = report.assemble(collected, agent_version=__version__, collected_at=collected_at, consented_at=collected_at,
                          benchmarks=benches, benchmark_skipped_reason=skipped)
    if problems := report.errors(doc):
        print("진단 결과가 스키마와 맞지 않아 올리지 않아요:\n  " + "\n  ".join(problems), file=sys.stderr)
        _save(doc, args.out)
        return 1
    print(report.summary(doc, collected.get("checks")))
    if args.code is None:
        _save(doc, args.out)
        print("페어링 코드가 없어 올리지 않았어요.")
        return 0
    print(_target(api))
    if ask("\n이 결과를 올릴까요? [y/N] ").strip().lower() != "y":
        print("올리지 않았어요.")
        return 0
    doc["consentedAt"] = clock()
    return _upload(api, args.code, doc, args.out, post, sleep, str(uuid.uuid4()))


def _resend(args: argparse.Namespace, env: Mapping[str, str], ask: Callable[[str], str], post: upload.Post,
            sleep: upload.Sleep, clock: Callable[[], str]) -> int:
    """남긴 JSON을 다시 올린다. 진단을 다시 돌리지 않는다.

    키 파일이 있으면 이미 동의하고 보냈던 것이라 본문·키를 그대로 쓴다. 없으면 처음 보내는 것이라
    지금 동의한 시각을 consentedAt에 적고 새 키를 만든다."""
    api = env.get("TRACE_API_URL", "").rstrip("/")
    if (code := _check_api(api, args.code)) is not None:
        return code
    try:
        doc = json.loads(args.file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        print(f"진단 JSON을 읽지 못했어요: {err}", file=sys.stderr)
        return 2
    if problems := report.errors(doc):
        print("진단 결과가 스키마와 맞지 않아 올리지 않아요:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    print(report.summary(doc))
    print(_target(api))
    if ask("\n이 결과를 올릴까요? [y/N] ").strip().lower() != "y":
        print("올리지 않았어요.")
        return 0
    key_file = _key_file(args.file)
    key = key_file.read_text(encoding="utf-8").strip() if key_file.exists() else ""
    if not key:
        doc["consentedAt"] = clock()
        key = str(uuid.uuid4())
        _save(doc, args.file, key)  # 보내기 전에 바뀐 본문과 키를 함께 남겨, 어디서 끊겨도 다음에 같은 키로 올린다
    return _upload(api, args.code, doc, args.file, post, sleep, key)


def main(argv: list[str] | None = None, *, env: Mapping[str, str] | None = None, ask: Callable[[str], str] = input,
         run: commands.Runner = commands.run, post: upload.Post = upload.http_post, workloads: Any = None,
         clock: Callable[[], str] = macos.iso_now, system: str = sys.platform,
         sleep: upload.Sleep = upload.time.sleep) -> int:
    multiprocessing.freeze_support()  # PyInstaller 단일 실행 파일에서 CPU_MULTI가 프로세스를 끝없이 띄우지 않게
    args_list = sys.argv[1:] if argv is None else argv
    if not args_list:
        print(f"trace-agent {__version__}")
        return 0
    parser = argparse.ArgumentParser(prog="trace-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run", help="진단하고 동의하면 올린다")
    run_parser.add_argument("--code", help="관리자 화면의 6자리 페어링 코드")
    run_parser.add_argument("--out", type=Path, default=Path("trace-diagnostics.json"), help="JSON을 남길 파일")
    upload_parser = sub.add_parser("upload", help="올리지 못하고 남긴 JSON을 다시 올린다")
    upload_parser.add_argument("--code", required=True, help="관리자 화면의 새 6자리 페어링 코드")
    upload_parser.add_argument("--file", type=Path, default=Path("trace-diagnostics.json"), help="남긴 JSON 파일")
    args = parser.parse_args(args_list)
    environ = os.environ if env is None else env
    if args.command == "upload":
        return _resend(args, environ, ask, post, sleep, clock)
    args.system = system  # win32면 Windows 수집기(AG2), 그 밖은 macOS 수집기
    return _run(args, environ, ask, run, post, workloads, clock, sleep)


if __name__ == "__main__":
    raise SystemExit(main())
