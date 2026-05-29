from __future__ import annotations

from typing import Any

from loguru import logger

from app.common.signal_bus import signalBus


def emit_run_status(stage: str, detail: str = "", **fields: Any) -> None:
    """Send a user-facing automation status update to the UI."""
    payload = {
        "stage": stage,
        "detail": detail,
        **fields,
    }
    try:
        signalBus.runStatusChanged.emit(payload)
    except Exception as exc:
        logger.debug(f"运行状态提醒发送失败: {exc}")
