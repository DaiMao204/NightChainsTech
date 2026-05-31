from __future__ import annotations

import re
from typing import Union

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from qfluentwidgets import ConfigItem, FluentIconBase, PlainTextEdit, PushButton, SettingCard, qconfig

from app.common.config_change import emit_config_changed


class TextListSettingCard(SettingCard):
    """A compact multi-line editor for list-like ConfigItem values."""

    def __init__(
        self,
        configItem: ConfigItem,
        icon: Union[str, QIcon, FluentIconBase],
        title: str,
        content=None,
        *,
        placeholder: str = "",
        parent=None,
    ):
        super().__init__(icon, title, content, parent)
        self.configItem = configItem

        self.setFixedHeight(132)
        self.textEdit = PlainTextEdit(self)
        self.textEdit.setFixedSize(430, 86)
        self.textEdit.setPlaceholderText(placeholder)
        self.textEdit.setPlainText(self._format(qconfig.get(configItem) or []))

        self.saveButton = PushButton("保存", self)
        self.saveButton.clicked.connect(self.save)

        self.hBoxLayout.addWidget(self.textEdit, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(8)
        self.hBoxLayout.addWidget(self.saveButton, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _format(self, value) -> str:
        if not isinstance(value, (list, tuple, set)):
            return ""
        return "\n".join(str(item).strip() for item in value if str(item).strip())

    def _parse(self) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        text = self.textEdit.toPlainText()
        for item in re.split(r"[\n;,；，]+", text):
            value = item.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def save(self):
        value = self._parse()
        qconfig.set(self.configItem, value)
        self.textEdit.setPlainText(self._format(value))
        emit_config_changed("配置已保存", f"{self.titleLabel.text()} 已更新")
