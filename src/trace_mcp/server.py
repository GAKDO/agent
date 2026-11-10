"""MCP 서버(stdio). 도구는 모두 읽기 전용이고 로그인한 사용자 권한으로만 게이트웨이를 부른다."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from trace_mcp import tools
from trace_mcp.client import ApiError, TraceClient

INSTRUCTIONS = (
    "TRACE 노트북 렌탈 서비스의 내 렌탈과 출고(OUT)·수령(RCV)·반납(RET) 시점별 외관 검사·진단 결과를 읽는다. "
    "렌탈 상태를 물으면 먼저 list_my_rentals로 rentalId를 찾고 summarize_rental로 답한다."
)
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)


def build(client: TraceClient) -> MCPServer:
    app = MCPServer(name="trace", instructions=INSTRUCTIONS)

    def run(fn: Any, *args: Any) -> Any:
        try:
            return fn(client, *args)
        except ApiError as err:
            return {"error": err.code, "status": err.status, "message": err.title}

    @app.tool(annotations=READ_ONLY)
    def whoami() -> Any:
        """로그인한 내 계정 정보."""
        return run(tools.whoami)

    @app.tool(annotations=READ_ONLY)
    def list_my_rentals(status: str | None = None) -> Any:
        """내 렌탈 목록(최근 순). status로 OPEN·CLOSED 등을 거를 수 있다."""
        return run(tools.list_my_rentals, status)

    @app.tool(annotations=READ_ONLY)
    def get_rental(rental_id: str) -> Any:
        """렌탈 하나와 출고·수령·반납 시점 상태(checkpointId 포함)."""
        return run(tools.get_rental, rental_id)

    @app.tool(annotations=READ_ONLY)
    def get_inspection(checkpoint_id: str) -> Any:
        """한 시점의 외관 검사 결과: 흠집, 이전 시점 대비 신규 판정, 등급."""
        return run(tools.get_inspection, checkpoint_id)

    @app.tool(annotations=READ_ONLY)
    def get_diagnostics(checkpoint_id: str) -> Any:
        """한 시점의 기기 진단 요약(배터리·SSD 등), 이전 시점 비교, 점검 플래그."""
        return run(tools.get_diagnostics, checkpoint_id)

    @app.tool(annotations=READ_ONLY)
    def get_device_model(model_code: str) -> Any:
        """기종 정보와 치수(예: MBA13-M2)."""
        return run(tools.get_device_model, model_code)

    @app.tool(annotations=READ_ONLY)
    def summarize_rental(rental_id: str) -> Any:
        """렌탈 하나의 시점별 상태·검사·진단을 한 번에 모은 요약. '내 렌탈 지금 어때?'에 쓴다."""
        return run(tools.summarize_rental, rental_id)

    return app
