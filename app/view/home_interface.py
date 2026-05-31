"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-04-02 19:12:22
LastEditTime: 2025-02-11 19:08:33
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import ScrollArea, SettingCard

from app.common.run_status_display import format_profit_status
from app.common.signal_bus import signalBus
from app.common.style_sheet import StyleSheet
from app.components.button_card import ButtonCardView
from core.control.control import stop as stop_control


def stop_all_tasks():
    from auto.run_business import stop as stop_run_business

    stop_control()
    stop_run_business()


class HomeInterface(ScrollArea):
    """Application overview."""

    def __init__(self, parent=None):
        super().__init__(parent=parent)

        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)
        self.titleLabel = QLabel("总览", self)
        self.runStatusCard = SettingCard(
            FIF.TRAIN,
            "运行状态",
            "等待开始",
            self.view,
        )
        self.runStatusCard.setFixedHeight(110)
        self.runStatusCard.contentLabel.setWordWrap(True)
        self.runStatusProfitLabel = QLabel("", self.runStatusCard)
        self.runStatusProfitLabel.setMinimumWidth(320)
        self.runStatusProfitLabel.setWordWrap(True)
        self.runStatusProfitLabel.hide()
        self.runStatusCard.hBoxLayout.addWidget(
            self.runStatusProfitLabel, 0, Qt.AlignmentFlag.AlignRight
        )
        self.runStatusCard.hBoxLayout.addSpacing(16)

        self.__initWidget()
        self.loadSamples()
        signalBus.runStatusChanged.connect(self.updateRunStatus)

    def __initWidget(self):
        self.view.setObjectName("view")
        self.titleLabel.setObjectName("galleryLabel")
        self.setObjectName("HomeInterface")
        StyleSheet.HOME_INTERFACE.apply(self)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setViewportMargins(0, 80, 0, 20)

        self.titleLabel.move(36, 30)
        self.vBoxLayout.setContentsMargins(36, 0, 36, 36)
        self.vBoxLayout.setSpacing(16)
        self.vBoxLayout.addWidget(self.runStatusCard)
        self.vBoxLayout.setAlignment(Qt.AlignmentFlag.AlignTop)

    def loadSamples(self):
        quickStartView = ButtonCardView("快速入口", parent=self.view)
        quickStartView.addSampleCard(
            icon=FIF.TRAIN,
            title="自动跑商",
            content="规划路线、查看利润并执行自动跑商",
            func=lambda: None,
            routekey="TwoCityRunnBusinessInterface",
        )
        quickStartView.addSampleCard(
            icon=FIF.GAME,
            title="设备连接",
            content="扫描模拟器并选择当前连接设备",
            func=lambda: None,
            routekey="ADBDataInterface",
        )
        quickStartView.addSampleCard(
            icon=FIF.CANCEL,
            title="停止当前脚本",
            content="停止正在执行的自动化流程",
            func=stop_all_tasks,
            routekey=None,
        )
        quickStartView.addSampleCard(
            icon=FIF.SETTING,
            title="设置",
            content="更新、设备地址和基础选项",
            func=lambda: None,
            routekey="SettingInterface",
        )
        self.vBoxLayout.addWidget(quickStartView)

    def updateRunStatus(self, status: dict):
        stage = str(status.get("stage") or "运行中")
        detail = str(status.get("detail") or "")
        route = str(status.get("route") or "")
        current_city = str(status.get("current_city") or "")
        target_city = str(status.get("target_city") or "")
        goods = status.get("goods") or []
        profit_text = format_profit_status(status)

        self.runStatusCard.titleLabel.setText(f"运行状态：{stage}")
        parts = []
        if route:
            parts.append(f"路线：{route}")
        if target_city:
            parts.append(f"目标：{target_city}")
        elif current_city:
            parts.append(f"城市：{current_city}")
        if goods:
            parts.append("商品：" + "、".join(str(good) for good in goods))
        if detail:
            parts.append(detail)
        self.runStatusCard.contentLabel.setText("  |  ".join(parts) or "等待开始")
        if not profit_text:
            self.runStatusProfitLabel.clear()
            self.runStatusProfitLabel.hide()
        else:
            self.runStatusProfitLabel.setText(profit_text)
            self.runStatusProfitLabel.show()
