"""명령줄 진입점.

    trace-agent                         버전
    trace-agent run                     진단하고 결과만 보여 주고 파일로 남긴다(올리지 않음)
    trace-agent run --code 482913       진단 → 결과 보기 → 동의하면 올린다
"""

from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import re
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from . import __version__, benchmark, commands, macos, report, upload


def _save(doc: dict[str, Any], out: Path) -> None:
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"진단 JSON을 {out}에 남겼어요.")


def _run(args: argparse.Namespace, env: Mapping[str, str], ask: Callable[[str], str], run: commands.Runner,
         post: upload.Post, workloads: Any, clock: Callable[[], str]) -> int:
    api = env.get("TRACE_API_URL", "").rstrip("/")
    if args.code is not None:
        if not re.fullmatch(r"\d{6}", args.code):
            print("페어링 코드는 6자리 숫자예요.", file=sys.stderr)
            return 2
        if not api:
            print("환경 변수가 없음: TRACE_API_URL", file=sys.stderr)
            return 2
    print("기기 정보를 읽는 중이에요...", flush=True)
    collected = macos.collect(run)
    if collected["conditions"]["acPower"]:
        print("벤치마크를 돌려요. 1분쯤 걸리니 전원을 연결한 채로 기다려 주세요.", flush=True)
    benches, skipped = benchmark.run(collected["conditions"]["acPower"], workloads,
                                     progress=lambda line: print("  " + line, flush=True))
    collected_at = clock()
    doc = report.assemble(collected, agent_version=__version__, collected_at=collected_at, consented_at=collected_at,
                          benchmarks=benches, benchmark_skipped_reason=skipped)
    if problems := report.errors(doc):
        print("진단 결과가 스키마와 맞지 않아 올리지 않아요:\n  " + "\n  ".join(problems), file=sys.stderr)
        _save(doc, args.out)
        return 1
    print(report.summary(doc))
    if args.code is None:
        _save(doc, args.out)
        print("페어링 코드가 없어 올리지 않았어요.")
        return 0
    if ask("\n이 결과를 올릴까요? [y/N] ").strip().lower() != "y":
        print("올리지 않았어요.")
        return 0
    doc["consentedAt"] = clock()
    try:
        token = upload.exchange(api, args.code, post)
        result = upload.send(api, token, doc, post)
    except upload.UploadError as err:
        print(f"올리지 못했어요: {err}", file=sys.stderr)
        _save(doc, args.out)
        return 1
    print(f"올렸어요. 점검 플래그 {len(result.get('flags', []))}개")
    return 0


def main(argv: list[str] | None = None, *, env: Mapping[str, str] | None = None, ask: Callable[[str], str] = input,
         run: commands.Runner = commands.run, post: upload.Post = upload.http_post, workloads: Any = None,
         clock: Callable[[], str] = macos.iso_now) -> int:
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
    args = parser.parse_args(args_list)
    return _run(args, os.environ if env is None else env, ask, run, post, workloads, clock)


if __name__ == "__main__":
    raise SystemExit(main())
