"""MCP 도구 본체(읽기 전용). 챗봇에서도 그대로 쓸 수 있게 MCP SDK와 떼어 둔다."""

from __future__ import annotations

import urllib.parse
from typing import Any

from trace_mcp.client import ApiError, TraceClient

CHECKPOINT_NAMES = {"OUT": "출고", "RCV": "수령", "RET": "반납"}  # contracts codes.yaml rental.checkpoint_type


def _seg(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def whoami(c: TraceClient) -> Any:
    return c.get("/auth/me")


def list_my_rentals(c: TraceClient, status: str | None = None) -> Any:
    return c.get("/rentals", {"status": status} if status else None)


def get_rental(c: TraceClient, rental_id: str) -> Any:
    return c.get(f"/rentals/{_seg(rental_id)}")


def get_inspection(c: TraceClient, checkpoint_id: str) -> Any:
    return c.get(f"/captures/checkpoints/{_seg(checkpoint_id)}/inspection")


def get_diagnostics(c: TraceClient, checkpoint_id: str) -> Any:
    return c.get(f"/diagnostics/checkpoints/{_seg(checkpoint_id)}")


def get_device_model(c: TraceClient, model_code: str) -> Any:
    return c.get(f"/device-models/{_seg(model_code)}")


def _or_reason(fn: Any, c: TraceClient, checkpoint_id: str) -> dict[str, Any]:
    """한 시점의 결과가 아직 없어도(404 등) 요약 전체가 실패하지 않게 사유를 담아 돌려준다."""
    try:
        return {"result": fn(c, checkpoint_id)}
    except ApiError as err:
        if err.status == 401:
            raise
        return {"result": None, "reason": err.code}


def summarize_rental(c: TraceClient, rental_id: str) -> dict[str, Any]:
    rental = get_rental(c, rental_id)
    checkpoints = []
    for cp in rental.get("checkpoints", []):
        item = {**cp, "name": CHECKPOINT_NAMES.get(cp.get("type", ""), cp.get("type"))}
        if cp.get("occurredAt"):  # 촬영이 끝난 시점만 결과가 있다
            item["inspection"] = _or_reason(get_inspection, c, cp["checkpointId"])
            item["diagnostics"] = _or_reason(get_diagnostics, c, cp["checkpointId"])
        checkpoints.append(item)
    return {**rental, "checkpoints": checkpoints}
