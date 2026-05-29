"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-04-10 22:54:08
LastEditTime: 2025-02-05 18:42:29
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

from functools import partial

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import ScrollArea, SettingCard

from app.common.config import cfg, qconfig
from app.common.config_change import emit_config_changed
from app.common.signal_bus import signalBus
from app.common.style_sheet import StyleSheet
from app.components.button_card import ButtonCardView
from app.utils.worker import Worker
from core.control.adb_port import EmulatorInfo, get_adb_port
from core.model.config import config


class ADBDataInterface(ScrollArea):
    """Device connection interface."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollWidget = QWidget(self)

        self.vBoxLayout = QVBoxLayout(self.scrollWidget)

        self.__initWidget()

    def __initWidget(self):
        self.setViewportMargins(0, 20, 0, 20)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName("ADBDataInterface")

        # initialize style sheet
        self.scrollWidget.setObjectName("scrollWidget")
        StyleSheet.SETTING_INTERFACE.apply(self)

        # initialize layout
        self.loadSamples()

    def showEvent(self, event):
        """当切换到该页面时，触发这个事件"""
        super().showEvent(event)
        self.basicInputView.removeAllSampleCards()
        self.basicInputView.set_title("正在扫描设备...")
        QTimer.singleShot(100, self.start_port_scan)

    def start_port_scan(self):
        """动画结束后调用的方法"""
        self.worker = Worker(get_adb_port)
        self.worker.result.connect(self.update_adb)
        self.worker.start()

    def loadSamples(self):
        """load samples"""
        self.currentDeviceCard = SettingCard(
            FIF.GAME,
            "当前连接设备",
            "",
            self.scrollWidget,
        )
        self.currentDeviceLabel = QLabel("", self.currentDeviceCard)
        self.currentDeviceLabel.setMinimumWidth(220)
        self.currentDeviceCard.hBoxLayout.addWidget(self.currentDeviceLabel)
        self.currentDeviceCard.hBoxLayout.addSpacing(16)

        self.basicInputView = ButtonCardView("正在扫描设备...", parent=self.scrollWidget)

        self.vBoxLayout.addWidget(self.currentDeviceCard)
        self.vBoxLayout.addWidget(self.basicInputView)
        self.update_current_device_card()

    def current_device(self) -> EmulatorInfo | None:
        device = qconfig.get(cfg.device)
        return device if isinstance(device, EmulatorInfo) else None

    def current_device_text(self) -> tuple[str, str]:
        device = self.current_device()
        if not device or not device.port:
            return "未选择设备", "请扫描设备或在设置中手动填写地址"
        return device.name or "自定义设备", f"127.0.0.1:{device.port}"

    def is_current_device(self, info: EmulatorInfo) -> bool:
        device = self.current_device()
        return bool(device and device.port and info.port == device.port)

    def update_current_device_card(self):
        name, address = self.current_device_text()
        self.currentDeviceCard.contentLabel.setText(name)
        self.currentDeviceLabel.setText(address)

    def mark_current_card(self, card):
        card.setObjectName("currentDeviceSampleCard")
        card.titleLabel.setText(f"{card.titleLabel.text()}  ·  当前连接")
        card.contentLabel.setText(f"已连接：{card.contentLabel.text()}")
        card.setStyleSheet(
            """
            #currentDeviceSampleCard {
                border: 2px solid #00a3d7;
                background-color: rgba(0, 163, 215, 28);
            }
            """
        )

    def update_adb(self, info_list: list[EmulatorInfo]):
        self.update_current_device_card()
        self.basicInputView.set_title("选择连接设备")
        has_device = False
        for info in info_list:
            if not info.port:
                continue
            has_device = True
            card = self.basicInputView.addSampleCard(
                icon=":/gallery/images/controls/Button.png",
                title=info.name,
                content=f"127.0.0.1:{info.port}",
                func=partial(self.set_port, info),
            )
            if self.is_current_device(info):
                self.mark_current_card(card)
        if not has_device:
            self.basicInputView.addSampleCard(
                icon=":/gallery/images/controls/Button.png",
                title="未发现模拟器",
                content="检查模拟器是否已启动，或手动填写设备地址",
                func=lambda: None,
                routekey="SettingInterface",
            )

    def set_port(self, info: EmulatorInfo):
        qconfig.set(cfg.device, info)
        self.update_current_device_card()
        emit_config_changed("设备连接已保存", f"{info.name}：127.0.0.1:{info.port}")
        signalBus.deviceConnected.emit()
        self.basicInputView.removeAllSampleCards()
        self.basicInputView.set_title("正在刷新设备状态...")
        QTimer.singleShot(100, self.start_port_scan)
