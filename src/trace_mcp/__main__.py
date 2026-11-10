"""trace-mcp [serve|login|logout]. 인자가 없으면 MCP 서버(stdio)를 띄운다."""

from __future__ import annotations

import argparse
import getpass
import sys

from trace_mcp.client import ApiError, TraceClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trace-mcp", description="TRACE 사용자용 MCP 서버")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "login", "logout"])
    args = parser.parse_args(argv)
    try:
        client = TraceClient()
    except ValueError as err:
        print(f"설정 오류: {err}", file=sys.stderr)
        return 1
    if args.command == "login":
        email = input("이메일: ").strip()
        try:
            role = client.login(email, getpass.getpass("비밀번호: "))
        except ApiError as err:
            print(f"로그인 실패: {err.title or err.code}", file=sys.stderr)
            return 1
        print(f"로그인됨({role}). 세션은 {client.path}에만 저장했습니다.")
        return 0
    if args.command == "logout":
        try:
            client.logout()
        except ApiError as err:
            print(f"서버 로그아웃은 실패했지만({err.code}) 이 컴퓨터의 세션은 지웠습니다.", file=sys.stderr)
            return 0
        print("로그아웃했습니다.")
        return 0
    from trace_mcp.server import build  # MCP SDK는 서버를 띄울 때만 불러온다

    build(client).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
