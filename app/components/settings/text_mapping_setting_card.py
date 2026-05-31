"""
Text mapping setting card for small dict-like planner options.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Union

from loguru import logger
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from qfluentwidgets import (
    ConfigItem,
    FluentIconBase,
    PlainTextEdit,
    PushButton,
    SettingCard,
    qconfig,
)

from app.common.config_change import emit_config_changed


MappingValueType = Literal["int", "bool"]


class TextMappingSettingCard(SettingCard):
    """A compact multi-line editor for ConfigItem dictionaries."""

    def __init__(
        self,
        configItem: ConfigItem,
        icon: Union[str, QIcon, FluentIconBase],
        title: str,
        content=None,
        *,
        value_type: MappingValueType,
        default_bool: bool | None = None,
        bool_false_only: bool = False,
        placeholder: str = "",
        parent=None,
    ):
        super().__init__(icon, title, content, parent)
        self.configItem = configItem
        self.value_type = value_type
        self.default_bool = default_bool
        self.bool_false_only = bool_false_only

        self.setFixedHeight(132)
        self.textEdit = PlainTextEdit(self)
        self.textEdit.setFixedSize(430, 86)
        self.textEdit.setPlaceholderText(placeholder)
        self.textEdit.setPlainText(self._format(qconfig.get(configItem) or {}))

        self.saveButton = PushButton("保存", self)
        self.saveButton.clicked.connect(self.save)

        self.hBoxLayout.addWidget(self.textEdit, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(8)
        self.hBoxLayout.addWidget(self.saveButton, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _format(self, value: dict[str, Any]) -> str:
        if not isinstance(value, dict):
            return ""
        lines: list[str] = []
        for key, item in value.items():
            if self.value_type == "bool":
                if self.bool_false_only:
                    if bool(item):
                        continue
                    lines.append(str(key))
                    continue
                text = "已解锁" if bool(item) else "未解锁"
            else:
                if isinstance(item, dict):
                    item = item.get("resonance", 0)
                text = str(int(item))
            lines.append(f"{key}={text}")
        return "\n".join(lines)

    def _items(self) -> list[str]:
        text = self.textEdit.toPlainText()
        return [item.strip() for item in re.split(r"[\n;,；，]+", text) if item.strip()]

    def _split_pair(self, item: str) -> tuple[str, str | None]:
        for delimiter in ("=", ":", "："):
            if delimiter in item:
                key, value = item.split(delimiter, 1)
                return key.strip(), value.strip()
        return item.strip(), None

    def _parse_bool(self, raw: str | None) -> bool:
        if raw is None:
            if self.default_bool is None:
                raise ValueError("missing bool value")
            return self.default_bool
        value = raw.strip().lower()
        if value in {"true", "1", "yes", "on", "已解锁", "解锁", "开启"}:
            return True
        if value in {"false", "0", "no", "off", "未解锁", "锁定", "关闭"}:
            return False
        raise ValueError(f"invalid bool value: {raw}")

    def _parse(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for item in self._items():
            key, value = self._split_pair(item)
            if not key:
                continue
            if self.value_type == "bool":
                result[key] = self._parse_bool(value)
            else:
                if value is None:
                    raise ValueError(f"missing int value: {key}")
                result[key] = int(value)
        return result

    def save(self):
        try:
            value = self._parse()
        except ValueError as exc:
            logger.warning(f"配置解析失败: {exc}")
            return
        qconfig.set(self.configItem, value)
        self.textEdit.setPlainText(self._format(value))
        emit_config_changed("配置已保存", f"{self.titleLabel.text()} 已更新")
