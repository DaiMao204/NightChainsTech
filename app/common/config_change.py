from __future__ import annotations

from loguru import logger

from app.common.signal_bus import signalBus


def emit_config_changed(title: str = "配置已更新", content: str = "") -> None:
    """Notify the UI that a user-facing config value was changed."""
    try:
        signalBus.configChanged.emit(title, content)
    except Exception as exc:
        logger.debug(f"配置变更提醒发送失败: {exc}")
