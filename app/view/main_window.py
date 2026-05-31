"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-04-02 19:27:03
LastEditTime: 2025-02-11 19:11:04
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""
from typing import Union

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QWidget
from loguru import logger
from qfluentwidgets import DotInfoBadge
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets import (
    InfoBadgePosition,
    InfoBar,
    InfoBarPosition,
    MSFluentWindow,
    NavigationItemPosition,
    SplashScreen,
    FluentIconBase,
    SystemThemeListener,
    isDarkTheme,
    setTheme,
    MessageBox
)

import app.common.resource  # 图标数据
from app.common.account_config import (
    account_config_auto_enabled,
    missing_account_config_reasons,
)
from app.common.config import VERSION, cfg, isWin11, qconfig
from app.common.signal_bus import signalBus
from app.components.update_message_box import UpdateMessageBox
from app.utils.constants import ICON_PATH, ROOT_PATH
from app.utils.utils import is_chinese
from app.utils.worker import Worker
from app.view.two_city_run_business_interface import TwoRunBusinessInterface
from core.control.control import adb_shell
from core.utils.utils import RESOURCES_PATH, read_json
from core.utils.update.manifest_update_utils import ManifestUpdateUtils, UpdateStatus

from .adb_data_interface import ADBDataInterface
from .home_interface import HomeInterface
from .logger_interface import LoggerInterface
from .setting_interface import SettingInterface


def configured_device_connected() -> bool:
    device = qconfig.get(cfg.device)
    if not getattr(device, "port", None):
        return False
    try:
        return "connected" in adb_shell("echo connected")
    except Exception as exc:
        logger.debug(f"启动设备连接检测失败: {exc}")
        return False


class MainWindow(MSFluentWindow):

    def __init__(self):
        super().__init__()
        self.wights = {}
        self._prestigePromptShown = False
        self.startupDeviceCheckWorker: Worker | None = None

        # 主题监听器
        self.themeListener = SystemThemeListener(self)

        self.initWindow()
        self.setInterface()

        self.initNavigation()
        self.initShortcuts()

        self.connectSignalToSlot()

        self.splashScreen.finish()
        # 检查更新
        self.updater = ManifestUpdateUtils()
        # self.checkUpdate()
        # 启用主题监听器
        self.themeListener.start()
        
        self.checkChinesePath()
        QTimer.singleShot(1200, self.checkStartupDeviceConnection)

    def connectSignalToSlot(self):
        signalBus.switchToCard.connect(self.switchToCard)
        signalBus.configChanged.connect(self.showConfigChanged)
        signalBus.deviceConnected.connect(self.onDeviceConnected)
        # 监听主题切换
        cfg.themeChanged.connect(setTheme)

    def initNavigation(self):
        self.addSubInterface(self.homeInterface, FIF.HOME, "总览")
        self.addSubInterface(self.two_run_business_interface, FIF.TRAIN, "自动跑商")
        self.addSubInterface(self.adb_data_interface, FIF.GAME, "设备连接")

        # 底部按钮
        self.addSubInterface(
            self.loggerInterface,
            FIF.ALIGNMENT,
            "日志",
            position=NavigationItemPosition.BOTTOM,
        )
        self.updateButton = self.navigationInterface.addItem(
            routeKey="Update",
            icon=FIF.UPDATE,
            text="更新",
            onClick=self._update,
            selectable=False,
            position=NavigationItemPosition.BOTTOM,
        )
        self.addSubInterface(
            self.settingInterface,
            FIF.SETTING,
            "设置",
            position=NavigationItemPosition.BOTTOM,
        )

    def initShortcuts(self):
        self.runBusinessShortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        self.runBusinessShortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.runBusinessShortcut.activated.connect(self.triggerRunBusinessShortcut)

    def triggerRunBusinessShortcut(self):
        self.switchTo(self.two_run_business_interface)
        QTimer.singleShot(120, self.two_run_business_interface.runPlannedBusiness)

    def initWindow(self):
        self.resize(960, 780)
        self.setMinimumWidth(760)
        self.setWindowIcon(QIcon(str(ICON_PATH / "logo.ico")))
        self.setWindowTitle(f"黑月科技 - {VERSION}")

        self.setMicaEffectEnabled(isWin11())
        self.setResizeEnabled(False)

        # create splash screen
        self.splashScreen = SplashScreen(self.windowIcon(), self)
        self.splashScreen.setIconSize(QSize(106, 106))
        self.splashScreen.raise_()

        desktop = self.screen().availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w // 2 - self.width() // 2, h // 2 - self.height() // 2)
        self.show()
        QApplication.processEvents()

    def setInterface(self):
        # create sub interface
        self.homeInterface = HomeInterface(self)
        self.loggerInterface = LoggerInterface(self)
        self.settingInterface = SettingInterface(self)
        self.two_run_business_interface = TwoRunBusinessInterface(self)
        self.adb_data_interface = ADBDataInterface(self)

        self.update_message_box = UpdateMessageBox(self)

    def addSubInterface(
        self,
        interface: QWidget,
        icon: Union[FluentIconBase, QIcon, str],
        text: str,
        selectedIcon=None,
        position=NavigationItemPosition.TOP,
        isTransparent=False,
    ):
        super().addSubInterface(
            interface, icon, text, selectedIcon, position, isTransparent
        )
        self.wights[interface.objectName()] = interface

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.splashScreen.resize(self.size())

    def switchToCard(self, routeKey):
        """切换到指定界面"""
        self.switchTo(self.wights[routeKey])

    def showConfigChanged(self, title: str, content: str):
        InfoBar.success(
            title=title or "配置已更新",
            content=content or "",
            orient=Qt.Orientation.Horizontal,
            isClosable=False,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self,
        )

    def onDeviceConnected(self):
        QTimer.singleShot(500, self.checkPrestigeConfig)

    def checkStartupDeviceConnection(self):
        if self._prestigePromptShown:
            return
        device = qconfig.get(cfg.device)
        if not getattr(device, "port", None):
            return
        self.startupDeviceCheckWorker = Worker(configured_device_connected)
        self.startupDeviceCheckWorker.result.connect(self.onStartupDeviceCheckResult)
        self.startupDeviceCheckWorker.finished.connect(self.onStartupDeviceCheckFinished)
        self.startupDeviceCheckWorker.start()

    def onStartupDeviceCheckResult(self, connected: bool):
        if connected:
            self.onDeviceConnected()

    def onStartupDeviceCheckFinished(self):
        if self.startupDeviceCheckWorker:
            self.startupDeviceCheckWorker.deleteLater()
        self.startupDeviceCheckWorker = None

    def missingPrestigeCities(self) -> list[str]:
        prestige_cities = self.prestigeCities()
        prestige_by_city = cfg.tradePlannerPrestigeByCity.value or {}
        if not isinstance(prestige_by_city, dict):
            return prestige_cities
        configured_cities = {
            self.prestigeMasterCity(str(city).strip())
            for city, level in prestige_by_city.items()
            if str(city).strip() and level not in (None, "")
        }
        return [city for city in prestige_cities if city not in configured_cities]

    def prestigeCities(self) -> list[str]:
        data = read_json(RESOURCES_PATH / "goods" / "CityPrestigeThresholds2026.json", {})
        cities = data.get("cities") if isinstance(data, dict) else {}
        if not isinstance(cities, dict):
            return []
        result: list[str] = []
        for city in cities.keys():
            master = self.prestigeMasterCity(str(city).strip())
            if master and master not in result:
                result.append(master)
        return result

    def prestigeMasterCity(self, city: str) -> str:
        attached = read_json(RESOURCES_PATH / "goods" / "AttachedToCityData.json", {})
        if isinstance(attached, dict):
            return str(attached.get(city) or city)
        return city

    def checkPrestigeConfig(self):
        if self._prestigePromptShown:
            return
        if not account_config_auto_enabled():
            return
        reasons = missing_account_config_reasons()
        if not reasons:
            return
        self._prestigePromptShown = True

        content = (
            "当前为账号配置自动读取模式，但货舱、主城声望或乘员共振配置不完整。\n"
            f"{'；'.join(reasons)}\n\n"
            "需要先读取账号配置，才能进行自动规划或跑商。"
        )
        w = MessageBox("需要读取账号配置", content, self)
        w.yesButton.setText("读取配置")
        w.cancelButton.setText("稍后")
        if w.exec():
            self.switchTo(self.two_run_business_interface)
            QTimer.singleShot(300, self.two_run_business_interface.focusAndAnalyzeAccountProfile)

    def closeEvent(self, e):
        # 停止监听器线程
        self.themeListener.terminate()
        self.themeListener.deleteLater()
        super().closeEvent(e)

    def _onThemeChangedFinished(self):
        super()._onThemeChangedFinished()

        # 云母特效启用时需要增加重试机制
        if self.isMicaEffectEnabled():
            QTimer.singleShot(100, lambda: self.windowEffect.setMicaEffect(self.winId(), isDarkTheme()))

    def _update(self):
        """
        检查更新
        """
        update_status = self.updater.get_update_status(reload=True)
        if update_status == UpdateStatus.UPDATE:
            self.update_message_box.show_update(self.updater.data)
        elif update_status == UpdateStatus.FAILED:
            InfoBar.error(
                title="检查更新失败",
                content="无法连接 GitHub，或最新 Release 中没有可用的 ZIP 更新包。",
                orient=Qt.Orientation.Horizontal,
                isClosable=False,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
        elif update_status == UpdateStatus.LATEST:
            InfoBar.success(
                title="当前已是最新版本",
                content="",
                orient=Qt.Orientation.Horizontal,
                isClosable=False,
                position=InfoBarPosition.TOP,
                duration=1000,
                parent=self,
            )
        else:
            InfoBar.error(
                title="检查更新失败",
                content="请稍后重试",
                orient=Qt.Orientation.Horizontal,
                isClosable=False,
                position=InfoBarPosition.TOP,
                duration=1000,
                parent=self,
            )

    def checkUpdate(self):
        update_status = self.updater.get_update_status()
        if update_status == UpdateStatus.UPDATE and self.updateButton is not None:
            self.updateBadge = DotInfoBadge.error(
                parent=self.navigationInterface,
                target=self.updateButton,
                position=InfoBadgePosition.NAVIGATION_ITEM,
            )
            self.updateBadge.setFixedSize(10, 10)

    def checkChinesePath(self):
        if is_chinese(str(ROOT_PATH)):
            w = MessageBox("兼容性警告", "程序运行在中文路径上，请移动至英文路径", self)
            
            w.yesButton.setText("知道了")
            w.cancelButton.hide()
            w.buttonLayout.insertStretch(1)
            w.exec()
