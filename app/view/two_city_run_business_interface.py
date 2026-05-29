"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-04-10 22:54:08
LastEditTime: 2025-02-10 23:25:35
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

from functools import partial
from typing import Dict, Optional

from loguru import logger
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import (
    CheckBox,
    ComboBox,
    ExpandLayout,
    ExpandSettingCard,
    InfoBar,
    MessageBox,
    PushButton,
    ScrollArea,
    SettingCard,
    SpinBox,
    SwitchSettingCard,
    qconfig,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.account_config import (
    account_config_auto_enabled,
    account_config_mode,
    missing_account_config_reasons,
)
from app.common.config import cfg
from app.common.config_change import emit_config_changed
from app.common.run_status_display import format_profit_status
from app.common.signal_bus import signalBus
from app.common.style_sheet import StyleSheet
from app.components.primary_push_load_card import PrimaryPushLoadCard
from app.components.settings.checkbox_group_card import CheckboxGroup
from app.components.settings.spin_box_setting_card import SpinBoxSettingCard
from app.components.settings.text_mapping_setting_card import TextMappingSettingCard
from app.utils.config import CITYS
from app.utils.worker import Worker

CITY_SELECTION_MODE_LABELS = {
    "auto": "自动规划",
    "manual": "手动选择",
}
CITY_SELECTION_MODE_VALUES = {
    label: value for value, label in CITY_SELECTION_MODE_LABELS.items()
}
ACCOUNT_CONFIG_MODE_LABELS = {
    "auto": "自动",
    "manual": "手动",
}
ACCOUNT_CONFIG_MODE_VALUES = {
    label: value for value, label in ACCOUNT_CONFIG_MODE_LABELS.items()
}
MIXED_CURRENCY_PRIORITY_LABELS = {
    "total": "综合优先",
    "tiemeng": "铁盟币优先",
    "jiaozi": "交子优先",
}
MIXED_CURRENCY_PRIORITY_VALUES = {
    label: value for value, label in MIXED_CURRENCY_PRIORITY_LABELS.items()
}
CANDIDATE_MODE_LABELS = {
    "best": "最优（不提供选项）",
    "three": "三选一",
    "five": "五选一",
}
CANDIDATE_MODE_VALUES = {
    label: value for value, label in CANDIDATE_MODE_LABELS.items()
}
CANDIDATE_MODE_COUNTS = {
    "best": 1,
    "three": 3,
    "five": 5,
}


class ManualRouteSettingCard(SettingCard):
    def __init__(self, parent=None):
        super().__init__(
            FIF.TRAIN,
            "手动双城",
            "选择往返的两座城市；去程和回程只是配置标签，实际执行会从当前更近的一端开始",
            parent,
        )
        self.startComboBox = ComboBox(self)
        self.targetComboBox = ComboBox(self)
        self.startComboBox.addItems(CITYS)
        self.targetComboBox.addItems(CITYS)
        self.startComboBox.setCurrentText(cfg.tradePlannerManualStartCity.value or (CITYS[0] if CITYS else ""))
        self.targetComboBox.setCurrentText(
            cfg.tradePlannerManualTargetCity.value
            or (CITYS[1] if len(CITYS) > 1 else (CITYS[0] if CITYS else ""))
        )

        self.outboundWidget = self._create_leg_widget(
            "去程",
            cfg.RunOutboundBook,
            cfg.RunOutboundHaggleNum,
        )
        self.returnWidget = self._create_leg_widget(
            "回程",
            cfg.RunReturnBook,
            cfg.RunReturnHaggleNum,
        )
        self.startComboBox.currentTextChanged.connect(self._set_start_city)
        self.targetComboBox.currentTextChanged.connect(self._set_target_city)

        self.hBoxLayout.addWidget(self.startComboBox, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addWidget(self.outboundWidget, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addWidget(self.returnWidget, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addWidget(self.targetComboBox, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.refreshPlanningControls()

    def _create_leg_widget(self, label: str, book_config, haggle_config) -> QWidget:
        widget = QWidget(self)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        title = QLabel(label, widget)
        bookLabel = QLabel("书", widget)
        haggleLabel = QLabel("抬砍", widget)
        autoBookLabel = QLabel("书自动规划", widget)
        autoHaggleLabel = QLabel("抬砍自动规划", widget)
        bookSpinBox = SpinBox(widget)
        haggleSpinBox = SpinBox(widget)
        bookSpinBox.setRange(0, 20)
        haggleSpinBox.setRange(0, 20)
        bookSpinBox.setFixedWidth(58)
        haggleSpinBox.setFixedWidth(58)
        bookSpinBox.setValue(book_config.value)
        haggleSpinBox.setValue(haggle_config.value)
        bookSpinBox.valueChanged.connect(
            lambda value, config=book_config, text=f"{label}进货书": self._set_leg_value(config, text, value)
        )
        haggleSpinBox.valueChanged.connect(
            lambda value, config=haggle_config, text=f"{label}抬砍": self._set_leg_value(config, text, value)
        )
        layout.addWidget(title)
        layout.addWidget(bookLabel)
        layout.addWidget(bookSpinBox)
        layout.addWidget(autoBookLabel)
        layout.addWidget(haggleLabel)
        layout.addWidget(haggleSpinBox)
        layout.addWidget(autoHaggleLabel)
        widget.bookLabel = bookLabel
        widget.bookSpinBox = bookSpinBox
        widget.autoBookLabel = autoBookLabel
        widget.haggleLabel = haggleLabel
        widget.haggleSpinBox = haggleSpinBox
        widget.autoHaggleLabel = autoHaggleLabel
        return widget

    def _set_leg_value(self, config, label: str, value: int):
        qconfig.set(config, value)
        emit_config_changed("跑商配置已保存", f"{label}：{value}")

    def _set_start_city(self, text: str):
        qconfig.set(cfg.tradePlannerManualStartCity, text)
        emit_config_changed("跑商配置已保存", f"起始城市：{text}")

    def _set_target_city(self, text: str):
        qconfig.set(cfg.tradePlannerManualTargetCity, text)
        emit_config_changed("跑商配置已保存", f"目标城市：{text}")

    def refreshPlanningControls(self):
        auto_book = bool(cfg.RunUsePlannerBook.value)
        auto_haggle = bool(cfg.RunUsePlannerHaggle.value)
        for widget in (self.outboundWidget, self.returnWidget):
            widget.bookLabel.setVisible(not auto_book)
            widget.bookSpinBox.setVisible(not auto_book)
            widget.autoBookLabel.setVisible(auto_book)
            widget.haggleLabel.setVisible(not auto_haggle)
            widget.haggleSpinBox.setVisible(not auto_haggle)
            widget.autoHaggleLabel.setVisible(auto_haggle)


class FatigueResourceSettingCard(SettingCard):
    def __init__(
        self,
        count_config,
        use_all_config,
        icon,
        title: str,
        content: str,
        *,
        max_count: int = 999,
        parent=None,
    ):
        super().__init__(icon, title, content, parent)
        self.countConfig = count_config
        self.useAllConfig = use_all_config
        self.useAllCheckBox = CheckBox("使用完", self)
        self.countSpinBox = SpinBox(self)
        self.countSpinBox.setRange(0, max_count)
        self.countSpinBox.setFixedWidth(76)
        self.countSpinBox.setValue(int(count_config.value or 0))
        self.useAllCheckBox.setChecked(bool(use_all_config.value))
        self.countSpinBox.setEnabled(not self.useAllCheckBox.isChecked())
        self.useAllCheckBox.toggled.connect(self._set_use_all)
        self.countSpinBox.valueChanged.connect(self._set_count)
        self.hBoxLayout.addWidget(self.useAllCheckBox, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addWidget(self.countSpinBox, 0, Qt.AlignmentFlag.AlignRight)
        self.hBoxLayout.addSpacing(16)

    def _set_use_all(self, checked: bool):
        qconfig.set(self.useAllConfig, checked)
        self.countSpinBox.setEnabled(not checked)
        emit_config_changed(
            "跑商配置已保存",
            f"{self.titleLabel.text()}：{'使用完' if checked else '按数量'}",
        )

    def _set_count(self, value: int):
        qconfig.set(self.countConfig, value)
        emit_config_changed("跑商配置已保存", f"{self.titleLabel.text()}：{value}")


class TwoRunBusinessInterface(ScrollArea):
    """跑商配置 interface"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.skillCardData: Dict[str, SpinBoxSettingCard] = {}
        self.planWorker: Optional[Worker] = None
        self.plannedRunWorker: Optional[Worker] = None
        self.accountProfileWorker: Optional[Worker] = None
        self.plannedRoute = None
        self.plannedSummary: Optional[dict] = None
        self.plannedRouteOptions: list[tuple[object, dict]] = []
        self.selectedRouteIndex: int = -1
        self.pendingRunAfterPlan = False
        self.scrollWidget = QWidget(self)
        self.expandLayout = ExpandLayout(self.scrollWidget)

        self.titleLabel = QLabel("跑商配置", self)

        self.__initWidget()

    def __initWidget(self):
        self.resize(1000, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 250, 0, 20)
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setObjectName("TwoCityRunnBusinessInterface")

        self.scrollWidget.setObjectName("scrollWidget")
        self.titleLabel.setObjectName("titleLabel")
        StyleSheet.VIEW_INTERFACE.apply(self)

        self.loadSamples()
        self.__initLayout()
        self.connectSignalToSlot()
        self.refreshConfigCards()
        self._update_city_checkbox_state()

    def loadSamples(self):
        """load samples"""
        self.citySelectionModeCard = SettingCard(
            FIF.TAG,
            "城市选择方式",
            "自动规划会在勾选城市中选择路线；手动选择只在两座城市之间往返",
            self.scrollWidget,
        )
        self.citySelectionModeComboBox = ComboBox(self.citySelectionModeCard)
        self.citySelectionModeComboBox.addItems(list(CITY_SELECTION_MODE_LABELS.values()))
        selection_mode = self._city_selection_mode()
        self.citySelectionModeComboBox.setCurrentText(
            CITY_SELECTION_MODE_LABELS[selection_mode]
        )
        self.citySelectionModeCard.hBoxLayout.addWidget(
            self.citySelectionModeComboBox, 0, Qt.AlignmentFlag.AlignRight
        )
        self.citySelectionModeCard.hBoxLayout.addSpacing(16)

        self.cityCheckboxGroup = CheckboxGroup(self.scrollWidget)
        selected_cities = set(cfg.tradePlannerIncludeCities.value or CITYS)
        unavailable_cities = set(cfg.tradePlannerUnavailableCities.value or [])
        for city in CITYS:
            checkbox = self.cityCheckboxGroup.addCheckbox(city)
            checkbox.setChecked(city in selected_cities and city not in unavailable_cities)
            checkbox.toggled.connect(partial(self.check_checkbox, checkbox))
        self.manualRouteCard = ManualRouteSettingCard(self.scrollWidget)

        self.runStatusCard = SettingCard(
            FIF.TRAIN,
            "运行状态",
            "等待开始",
            self,
        )
        self.runStatusCard.setFixedHeight(150)
        self.runStatusCard.contentLabel.setWordWrap(True)
        self.runStatusActionPanel = QWidget(self.runStatusCard)
        self.runStatusActionPanel.setFixedWidth(360)
        self.runStatusActionLayout = QVBoxLayout(self.runStatusActionPanel)
        self.runStatusActionLayout.setContentsMargins(0, 0, 0, 0)
        self.runStatusActionLayout.setSpacing(8)
        self.runStatusProfitLabel = QLabel("", self.runStatusActionPanel)
        self.runStatusProfitLabel.setWordWrap(True)
        self.runStatusProfitLabel.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.runStatusProfitLabel.hide()
        self.runStatusButtonPanel = QWidget(self.runStatusActionPanel)
        self.runStatusButtonLayout = QHBoxLayout(self.runStatusButtonPanel)
        self.runStatusButtonLayout.setContentsMargins(0, 0, 0, 0)
        self.runStatusButtonLayout.setSpacing(8)
        self.runActionButton = PushButton("执行", self.runStatusButtonPanel)
        self.runActionButton.setFixedWidth(72)
        self.stopRunButton = PushButton("停止", self.runStatusButtonPanel)
        self.stopRunButton.setFixedWidth(72)
        self.stopRunButton.setEnabled(False)
        self.runStatusButtonLayout.addStretch(1)
        self.runStatusButtonLayout.addWidget(self.runActionButton)
        self.runStatusButtonLayout.addWidget(self.stopRunButton)
        self.runStatusActionLayout.addWidget(self.runStatusProfitLabel, 1)
        self.runStatusActionLayout.addWidget(self.runStatusButtonPanel, 0)
        self.runStatusCard.hBoxLayout.addWidget(
            self.runStatusActionPanel, 0, Qt.AlignmentFlag.AlignRight
        )
        self.runStatusCard.hBoxLayout.addSpacing(16)

        self.planBusinessCard = PrimaryPushLoadCard(
            "规划",
            FIF.TAG,
            "自动规划",
            "根据实时市场数据计算推荐跑商路线",
            self.scrollWidget,
        )
        self.accountConfigModeCard = SettingCard(
            FIF.SEARCH,
            "账号配置读取",
            "自动模式会在缺少配置时先读取账号，并在跑商中自动维护商品解锁状态；手动模式按现有配置或默认值运行",
            self.scrollWidget,
        )
        self.accountConfigModeComboBox = ComboBox(self.accountConfigModeCard)
        self.accountConfigModeComboBox.addItems(list(ACCOUNT_CONFIG_MODE_LABELS.values()))
        mode = self._account_config_mode()
        self.accountConfigModeComboBox.setCurrentText(ACCOUNT_CONFIG_MODE_LABELS[mode])
        self.accountConfigModeCard.hBoxLayout.addWidget(
            self.accountConfigModeComboBox, 0, Qt.AlignmentFlag.AlignRight
        )
        self.accountConfigModeCard.hBoxLayout.addSpacing(16)
        self.plannerGroup = ExpandSettingCard(
            FIF.EDIT,
            "规划参数",
            "市场、货舱、声望和商品解锁",
            parent=self.scrollWidget,
        )
        self.plannerMaxLotCard = SpinBoxSettingCard(
            cfg.tradePlannerMaxLot,
            FIF.PENCIL_INK,
            "最大货舱数",
            "规划器用于估算可购买数量",
            spin_box_max=5000,
            parent=self.plannerGroup,
        )
        self.plannerMaxRestockCard = SpinBoxSettingCard(
            cfg.tradePlannerMaxRestock,
            FIF.PENCIL_INK,
            "自动规划最大进货书",
            "启用自动规划时，规划器会在 0 到该值之间选择推荐书量",
            spin_box_max=20,
            parent=self.plannerGroup,
        )
        self.mixedCurrencyPriorityCard = SettingCard(
            FIF.TAG,
            "武林源收益优先级",
            "包含武林源时决定综合、交子或铁盟币优先",
            self.scrollWidget,
        )
        self.mixedCurrencyPriorityComboBox = ComboBox(self.mixedCurrencyPriorityCard)
        self.mixedCurrencyPriorityComboBox.addItems(
            list(MIXED_CURRENCY_PRIORITY_LABELS.values())
        )
        priority = self._mixed_currency_priority()
        self.mixedCurrencyPriorityComboBox.setCurrentText(
            MIXED_CURRENCY_PRIORITY_LABELS[priority]
        )
        self.mixedCurrencyPriorityCard.hBoxLayout.addWidget(
            self.mixedCurrencyPriorityComboBox, 0, Qt.AlignmentFlag.AlignRight
        )
        self.mixedCurrencyPriorityCard.hBoxLayout.addSpacing(16)
        self.candidateModeCard = SettingCard(
            FIF.TAG,
            "候选路线数量",
            "默认只使用最优路线；三选一或五选一会显示候选路线",
            self.scrollWidget,
        )
        self.candidateModeComboBox = ComboBox(self.candidateModeCard)
        self.candidateModeComboBox.addItems(list(CANDIDATE_MODE_LABELS.values()))
        candidate_mode = self._candidate_mode()
        self.candidateModeComboBox.setCurrentText(CANDIDATE_MODE_LABELS[candidate_mode])
        self.candidateModeCard.hBoxLayout.addWidget(
            self.candidateModeComboBox, 0, Qt.AlignmentFlag.AlignRight
        )
        self.candidateModeCard.hBoxLayout.addSpacing(16)
        self.routeCandidateCards: list[SettingCard] = []
        self.routeCandidateButtons: list[PushButton] = []
        for index in range(5):
            card = SettingCard(
                FIF.TRAIN,
                f"候选路线 {index + 1}",
                "等待规划",
                self.scrollWidget,
            )
            card.contentLabel.setWordWrap(True)
            card.setFixedHeight(168)
            button = PushButton("选择", card)
            button.setFixedWidth(72)
            button.clicked.connect(partial(self.selectRouteCandidate, index))
            card.hBoxLayout.addWidget(button, 0, Qt.AlignmentFlag.AlignRight)
            card.hBoxLayout.addSpacing(16)
            card.hide()
            self.routeCandidateCards.append(card)
            self.routeCandidateButtons.append(button)
        self.defaultPrestigeCard = SpinBoxSettingCard(
            cfg.tradePlannerDefaultPrestigeLevel,
            FIF.ACCEPT,
            "默认声望等级",
            "未单独配置城市时使用",
            spin_box_max=20,
            parent=self.plannerGroup,
        )
        self.prestigeByCityCard = TextMappingSettingCard(
            cfg.tradePlannerPrestigeByCity,
            FIF.DICTIONARY,
            "城市声望",
            "城市=等级",
            value_type="int",
            placeholder="武林源=20\n7号自由港=20",
            parent=self.plannerGroup,
        )
        self.productUnlockStatusCard = TextMappingSettingCard(
            cfg.tradePlannerProductUnlockStatus,
            FIF.DOCUMENT,
            "未解锁商品",
            "每行填写 城市/商品；默认所有商品已解锁",
            value_type="bool",
            default_bool=False,
            bool_false_only=True,
            placeholder="武林源/明前龙井\n7号自由港/货物名",
            parent=self.plannerGroup,
        )
        self.plannerGroup.viewLayout.addWidget(self.plannerMaxLotCard)
        self.plannerGroup.viewLayout.addWidget(self.plannerMaxRestockCard)
        self.plannerGroup.viewLayout.addWidget(self.defaultPrestigeCard)
        self.plannerGroup.viewLayout.addWidget(self.prestigeByCityCard)
        self.plannerGroup.viewLayout.addWidget(self.productUnlockStatusCard)

        self.fatigueGroup = ExpandSettingCard(
            FIF.EDIT,
            "疲劳设置",
            "体力不足时按配置恢复；未启用恢复资源时会停止跑商",
            parent=self.scrollWidget,
        )
        self.allowFoodCard = SwitchSettingCard(
            FIF.SYNC,
            "便当柜",
            "允许体力不足时优先吃便当",
            cfg.RunAllowFood,
            self.fatigueGroup,
        )
        self.useStrengthMedicineCard = SwitchSettingCard(
            FIF.SYNC,
            "使用体力药",
            "体力不足弹窗出现时再使用体力药",
            cfg.RunUseStrengthMedicine,
            self.fatigueGroup,
        )
        self.lollipopCard = FatigueResourceSettingCard(
            cfg.RunStrengthLollipopCount,
            cfg.RunStrengthLollipopUseAll,
            FIF.PENCIL_INK,
            "提神棒棒糖",
            "每个恢复 60 疲劳",
            parent=self.fatigueGroup,
        )
        self.gumCard = FatigueResourceSettingCard(
            cfg.RunStrengthGumCount,
            cfg.RunStrengthGumUseAll,
            FIF.PENCIL_INK,
            "提神口香糖",
            "每个恢复 100 疲劳",
            parent=self.fatigueGroup,
        )
        self.cactusCandyCard = FatigueResourceSettingCard(
            cfg.RunStrengthCactusCandyCount,
            cfg.RunStrengthCactusCandyUseAll,
            FIF.PENCIL_INK,
            "仙人掌提神跳糖",
            "每个恢复 900 疲劳",
            parent=self.fatigueGroup,
        )
        self.useHuashiCard = SwitchSettingCard(
            FIF.SYNC,
            "桦石",
            "每天最多 8 次，每次恢复 150 疲劳，消耗会逐渐增加",
            cfg.RunUseHuashi,
            self.fatigueGroup,
        )
        self.huashiCard = FatigueResourceSettingCard(
            cfg.RunHuashiCount,
            cfg.RunHuashiUseAll,
            FIF.PENCIL_INK,
            "桦石次数",
            "每日上限 8 次",
            max_count=8,
            parent=self.fatigueGroup,
        )
        self.allowDrinkCard = SwitchSettingCard(
            FIF.SYNC,
            "喝酒",
            "允许在支持喝酒的主城把每日酒喝光",
            cfg.RunAllowDrink,
            self.fatigueGroup,
        )
        self.fatigueGroup.viewLayout.addWidget(self.allowFoodCard)
        self.fatigueGroup.viewLayout.addWidget(self.useStrengthMedicineCard)
        self.fatigueGroup.viewLayout.addWidget(self.lollipopCard)
        self.fatigueGroup.viewLayout.addWidget(self.gumCard)
        self.fatigueGroup.viewLayout.addWidget(self.cactusCandyCard)
        self.fatigueGroup.viewLayout.addWidget(self.useHuashiCard)
        self.fatigueGroup.viewLayout.addWidget(self.huashiCard)
        self.fatigueGroup.viewLayout.addWidget(self.allowDrinkCard)

        self.bookGroup = ExpandSettingCard(
            FIF.EDIT,
            "进货书设置",
            "所有城市共用",
            parent=self.scrollWidget,
        )
        self.usePlannerBookCard = SwitchSettingCard(
            FIF.SYNC,
            "自动规划",
            "按照最高综合参考利润推荐的书量执行",
            cfg.RunUsePlannerBook,
            self.bookGroup,
        )
        self.outboundBookCard = SpinBoxSettingCard(
            cfg.RunOutboundBook,
            FIF.PENCIL_INK,
            "去程固定进货书",
            "关闭自动规划时，起始城市买入使用",
            spin_box_max=20,
            parent=self.bookGroup,
        )
        self.returnBookCard = SpinBoxSettingCard(
            cfg.RunReturnBook,
            FIF.PENCIL_INK,
            "回程固定进货书",
            "关闭自动规划时，目标城市买入使用",
            spin_box_max=20,
            parent=self.bookGroup,
        )
        self.bookGroup.viewLayout.addWidget(self.usePlannerBookCard)
        self.bookGroup.viewLayout.addWidget(self.outboundBookCard)
        self.bookGroup.viewLayout.addWidget(self.returnBookCard)

        self.haggleGroup = ExpandSettingCard(
            FIF.EDIT,
            "议价设置",
            "所有城市共用",
            parent=self.scrollWidget,
        )
        self.usePlannerHaggleCard = SwitchSettingCard(
            FIF.SYNC,
            "自动规划",
            "按综合参考利润决定是否抬砍；需要时按满 20% 执行",
            cfg.RunUsePlannerHaggle,
            self.haggleGroup,
        )
        self.outboundHaggleCard = SpinBoxSettingCard(
            cfg.RunOutboundHaggleNum,
            FIF.PENCIL_INK,
            "去程固定抬砍成功次数",
            "关闭自动规划时，起始城市买入和目标城市卖出使用；达到 20% 后会自动停止",
            spin_box_max=20,
            parent=self.haggleGroup,
        )
        self.returnHaggleCard = SpinBoxSettingCard(
            cfg.RunReturnHaggleNum,
            FIF.PENCIL_INK,
            "回程固定抬砍成功次数",
            "关闭自动规划时，目标城市买入和起始城市卖出使用；达到 20% 后会自动停止",
            spin_box_max=20,
            parent=self.haggleGroup,
        )
        self.haggleGroup.viewLayout.addWidget(self.usePlannerHaggleCard)
        self.haggleGroup.viewLayout.addWidget(self.outboundHaggleCard)
        self.haggleGroup.viewLayout.addWidget(self.returnHaggleCard)

    def _account_config_mode(self) -> str:
        mode = account_config_mode()
        return mode if mode in ACCOUNT_CONFIG_MODE_LABELS else "auto"

    def _set_account_config_mode(self, text: str):
        mode = ACCOUNT_CONFIG_MODE_VALUES.get(text, "auto")
        qconfig.set(cfg.tradePlannerAccountConfigMode, mode)
        try:
            from core.model import app

            app.TradePlanner.AccountConfigMode = mode
        except Exception as exc:
            logger.debug(f"同步运行时账号配置读取模式失败: {exc}")
        emit_config_changed("跑商配置已保存", f"账号配置读取：{text}")
        if mode == "manual":
            self.updateRunStatus(
                {
                    "stage": "账号配置手动模式",
                    "detail": "将按现有配置运行，缺失项使用默认值，跑商中不会自动写回账号配置",
                }
            )
        elif missing_account_config_reasons():
            self.updateRunStatus(
                {"stage": "需要读取账号配置", "detail": "自动模式下需要先补齐货舱和主城声望"}
            )

    def _city_selection_mode(self) -> str:
        mode = cfg.tradePlannerCitySelectionMode.value or "auto"
        return mode if mode in CITY_SELECTION_MODE_LABELS else "auto"

    def _set_city_selection_mode(self, text: str):
        mode = CITY_SELECTION_MODE_VALUES.get(text, "auto")
        qconfig.set(cfg.tradePlannerCitySelectionMode, mode)
        try:
            from core.model import app

            app.TradePlanner.CitySelectionMode = mode
        except Exception as exc:
            logger.debug(f"同步运行时城市选择方式失败: {exc}")
        emit_config_changed("跑商配置已保存", f"城市选择方式：{text}")
        self._update_city_checkbox_state()
        self._clear_planned_route()

    def _mixed_currency_priority(self) -> str:
        priority = cfg.tradePlannerMixedCurrencyPriority.value or "total"
        return priority if priority in MIXED_CURRENCY_PRIORITY_LABELS else "total"

    def _set_mixed_currency_priority(self, text: str):
        priority = MIXED_CURRENCY_PRIORITY_VALUES.get(text, "total")
        qconfig.set(cfg.tradePlannerMixedCurrencyPriority, priority)
        emit_config_changed("跑商配置已保存", f"武林源收益优先级：{text}")

    def _candidate_mode(self) -> str:
        mode = cfg.tradePlannerCandidateMode.value or "best"
        return mode if mode in CANDIDATE_MODE_LABELS else "best"

    def _candidate_count(self) -> int:
        return CANDIDATE_MODE_COUNTS[self._candidate_mode()]

    def _set_candidate_mode(self, text: str):
        mode = CANDIDATE_MODE_VALUES.get(text, "best")
        qconfig.set(cfg.tradePlannerCandidateMode, mode)
        emit_config_changed("跑商配置已保存", f"候选路线数量：{text}")
        self._rebuildLayout()

    def _update_city_checkbox_state(self):
        manual = self._city_selection_mode() == "manual"
        unavailable_cities = set(cfg.tradePlannerUnavailableCities.value or [])
        checkboxes = self.cityCheckboxGroup.checkboxGroup
        for checkbox in checkboxes:
            checkbox.setEnabled(not manual and checkbox.text() not in unavailable_cities)
            if checkbox.text() in unavailable_cities:
                checkbox.setChecked(False)
        self.cityCheckboxGroup.setVisible(not manual)
        self.manualRouteCard.setVisible(manual)
        if hasattr(self, "expandLayout"):
            self._rebuildLayout()

    def check_checkbox(self, checkbox: CheckBox, checked: bool):
        if self._city_selection_mode() == "manual":
            checkbox.setChecked(False)
            return
        if checkbox.text() in set(cfg.tradePlannerUnavailableCities.value or []) and checked:
            checkbox.setChecked(False)
            InfoBar.warning(
                title="",
                content=f"{checkbox.text()} 当前记录为未开放城市，已从自动规划中排除",
                orient=Qt.Orientation.Horizontal,
                isClosable=False,
                parent=self,
            )
            return
        selected = [
            item.text()
            for item in self.cityCheckboxGroup.checkboxGroup
            if item.isChecked()
        ]
        qconfig.set(cfg.tradePlannerIncludeCities, selected)
        emit_config_changed("跑商配置已保存", f"自动规划城市：{len(selected)} 个")

    def __initLayout(self):
        self.fatigueGroup._adjustViewSize()
        self.bookGroup._adjustViewSize()
        self.haggleGroup._adjustViewSize()
        self.plannerGroup._adjustViewSize()

        self.expandLayout.setContentsMargins(36, 0, 36, 0)
        self._rebuildLayout()
        self._position_top_widgets()

    def _layout_widgets(self) -> list[QWidget]:
        if self.plannedRouteOptions and self._candidate_count() > 1:
            top_widgets = [
                *self.routeCandidateCards,
                self.planBusinessCard,
                self.accountConfigModeCard,
                self.citySelectionModeCard,
                self.cityCheckboxGroup,
                self.manualRouteCard,
                self.mixedCurrencyPriorityCard,
                self.candidateModeCard,
            ]
        else:
            top_widgets = [
                self.planBusinessCard,
                self.accountConfigModeCard,
                self.citySelectionModeCard,
                self.cityCheckboxGroup,
                self.manualRouteCard,
                self.mixedCurrencyPriorityCard,
                self.candidateModeCard,
                *self.routeCandidateCards,
            ]
        return [
            *top_widgets,
            self.plannerGroup,
            self.fatigueGroup,
            self.bookGroup,
            self.haggleGroup,
        ]

    def _rebuildLayout(self):
        widgets = self._layout_widgets()
        layout_widgets = getattr(self.expandLayout, "_ExpandLayout__widgets", None)
        if isinstance(layout_widgets, list):
            known_widgets = set(layout_widgets)
            for widget in widgets:
                if widget not in known_widgets:
                    widget.installEventFilter(self.expandLayout)
            layout_widgets[:] = widgets
        else:
            for widget in widgets:
                self.expandLayout.addWidget(widget)
        self.expandLayout.invalidate()
        self.expandLayout.activate()
        self.scrollWidget.updateGeometry()

    def _scroll_to_config_top(self):
        self.verticalScrollBar().setValue(0)

    def _position_top_widgets(self):
        self.titleLabel.move(36, 30)
        self.titleLabel.raise_()
        if hasattr(self, "runStatusCard"):
            self.runStatusCard.setGeometry(36, 80, max(320, self.width() - 72), 150)
            self.runStatusCard.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_top_widgets()

    def connectSignalToSlot(self):
        self.accountConfigModeComboBox.currentTextChanged.connect(
            self._set_account_config_mode
        )
        self.citySelectionModeComboBox.currentTextChanged.connect(
            self._set_city_selection_mode
        )
        self.mixedCurrencyPriorityComboBox.currentTextChanged.connect(
            self._set_mixed_currency_priority
        )
        self.candidateModeComboBox.currentTextChanged.connect(
            self._set_candidate_mode
        )
        self.planBusinessCard.clicked.connect(self.planBusiness)
        self.runActionButton.clicked.connect(self.runPlannedBusiness)
        self.stopRunButton.clicked.connect(self.stopRunning)
        self.usePlannerBookCard.checkedChanged.connect(
            lambda checked: (
                emit_config_changed(
                    "跑商配置已保存",
                    f"进货书自动规划：{'开启' if checked else '关闭'}",
                ),
                self.manualRouteCard.refreshPlanningControls(),
                self._clear_planned_route(),
            )
        )
        self.usePlannerHaggleCard.checkedChanged.connect(
            lambda checked: (
                emit_config_changed(
                    "跑商配置已保存",
                    f"议价自动规划：{'开启' if checked else '关闭'}",
                ),
                self.manualRouteCard.refreshPlanningControls(),
                self._clear_planned_route(),
            )
        )
        self.useStrengthMedicineCard.checkedChanged.connect(
            lambda checked: (
                emit_config_changed(
                    "跑商配置已保存",
                    f"使用体力药：{'开启' if checked else '关闭'}",
                ),
                self.refreshFatigueCards(),
            )
        )
        self.useHuashiCard.checkedChanged.connect(
            lambda checked: (
                emit_config_changed(
                    "跑商配置已保存",
                    f"桦石恢复：{'开启' if checked else '关闭'}",
                ),
                self.refreshFatigueCards(),
            )
        )
        self.allowFoodCard.checkedChanged.connect(
            lambda checked: emit_config_changed(
                "跑商配置已保存",
                f"便当柜：{'允许' if checked else '不使用'}",
            )
        )
        self.allowDrinkCard.checkedChanged.connect(
            lambda checked: emit_config_changed(
                "跑商配置已保存",
                f"喝酒：{'允许' if checked else '不使用'}",
            )
        )
        signalBus.configChanged.connect(self.onConfigChanged)
        signalBus.runStatusChanged.connect(self.updateRunStatus)

    def updateRunStatus(self, status: dict):
        stage = str(status.get("stage") or "运行中")
        detail = str(status.get("detail") or "")
        route = str(status.get("route") or "")
        route_summary = str(status.get("route_summary") or "")
        current_city = str(status.get("current_city") or "")
        target_city = str(status.get("target_city") or "")
        profit_text = format_profit_status(status)

        self.runStatusCard.titleLabel.setText(f"运行状态：{stage}")
        parts = []
        if route_summary:
            parts.append(route_summary)
        elif route:
            parts.append(f"路线：{route}")
        if target_city:
            parts.append(f"目标：{target_city}")
        elif current_city:
            parts.append(f"城市：{current_city}")
        if detail:
            parts.append(detail)
        self.runStatusCard.contentLabel.setText("  |  ".join(parts) or "等待开始")
        if not profit_text:
            self.runStatusProfitLabel.clear()
            self.runStatusProfitLabel.hide()
        else:
            self.runStatusProfitLabel.setText(profit_text)
            self.runStatusProfitLabel.show()

    def onConfigChanged(self, *_):
        self.refreshConfigCards()
        self._clear_planned_route()

    def _clear_planned_route(self):
        self.plannedRoute = None
        self.plannedSummary = None
        self.plannedRouteOptions = []
        self.selectedRouteIndex = -1
        for index, card in enumerate(getattr(self, "routeCandidateCards", [])):
            card.titleLabel.setText(f"候选路线 {index + 1}")
            card.contentLabel.setText("等待规划")
            card.hide()
        for button in getattr(self, "routeCandidateButtons", []):
            button.setText("选择")
            button.setEnabled(True)
        if hasattr(self, "expandLayout"):
            self._rebuildLayout()

    def refreshConfigCards(self, *_):
        if hasattr(self, "manualRouteCard"):
            self.manualRouteCard.refreshPlanningControls()
        self.refreshFatigueCards()
        if hasattr(self, "outboundBookCard"):
            auto_book = bool(cfg.RunUsePlannerBook.value)
            self.outboundBookCard.setVisible(not auto_book)
            self.returnBookCard.setVisible(not auto_book)
        if hasattr(self, "outboundHaggleCard"):
            auto_haggle = bool(cfg.RunUsePlannerHaggle.value)
            self.outboundHaggleCard.setVisible(not auto_haggle)
            self.returnHaggleCard.setVisible(not auto_haggle)
        if hasattr(self, "prestigeByCityCard") and not self.prestigeByCityCard.textEdit.hasFocus():
            self.prestigeByCityCard.textEdit.setPlainText(
                self.prestigeByCityCard._format(cfg.tradePlannerPrestigeByCity.value or {})
            )
        if hasattr(self, "productUnlockStatusCard") and not self.productUnlockStatusCard.textEdit.hasFocus():
            self.productUnlockStatusCard.textEdit.setPlainText(
                self.productUnlockStatusCard._format(
                    cfg.tradePlannerProductUnlockStatus.value or {}
                )
            )

    def refreshFatigueCards(self):
        if not hasattr(self, "lollipopCard"):
            return
        use_medicine = bool(cfg.RunUseStrengthMedicine.value)
        for card in (self.lollipopCard, self.gumCard, self.cactusCandyCard):
            card.setVisible(use_medicine)
        self.huashiCard.setVisible(bool(cfg.RunUseHuashi.value))

    def _selected_cities(self) -> set[str] | None:
        if self._city_selection_mode() == "manual":
            return None
        cities = {
            checkbox.text()
            for checkbox in self.cityCheckboxGroup.checkboxGroup
            if checkbox.isChecked()
        }
        return cities or None

    def _manual_route_cities(self) -> tuple[str, str] | None:
        start = str(cfg.tradePlannerManualStartCity.value or "").strip()
        target = str(cfg.tradePlannerManualTargetCity.value or "").strip()
        if not start or not target or start == target:
            return None
        return start, target

    def _planner_kwargs(self) -> dict:
        product_unlock_status = {
            key: False
            for key, value in dict(cfg.tradePlannerProductUnlockStatus.value or {}).items()
            if value is False
        }
        product_unlock_status_by_city = {
            city: {
                good: False
                for good, value in dict(goods or {}).items()
                if value is False
            }
            for city, goods in dict(cfg.tradePlannerProductUnlockStatusByCity.value or {}).items()
            if isinstance(goods, dict)
        }
        product_unlock_status_by_city = {
            city: goods for city, goods in product_unlock_status_by_city.items() if goods
        }
        kwargs = {
            "api_url": cfg.tradePlannerApiUrl.value.strip() or None,
            "max_goods_num": cfg.tradePlannerMaxLot.value,
            "max_restock": (
                cfg.tradePlannerMaxRestock.value
                if cfg.RunUsePlannerBook.value
                else int(cfg.RunOutboundBook.value or 0) + int(cfg.RunReturnBook.value or 0)
            ),
            "default_prestige_level": cfg.tradePlannerDefaultPrestigeLevel.value,
            "prestige_by_city": dict(cfg.tradePlannerPrestigeByCity.value or {}),
            "product_unlock_status": product_unlock_status,
            "product_unlock_status_by_city": product_unlock_status_by_city,
            "use_default_product_unlock_status": False,
            "mixed_currency_priority": self._mixed_currency_priority(),
        }
        unavailable_cities = {
            str(city).strip()
            for city in (cfg.tradePlannerUnavailableCities.value or [])
            if str(city).strip()
        }
        if unavailable_cities:
            kwargs["exclude_cities"] = unavailable_cities

        if self._city_selection_mode() == "manual":
            manual_cities = self._manual_route_cities()
            if not manual_cities:
                return kwargs
            start_city, target_city = manual_cities
            kwargs["include_cities"] = {start_city, target_city}
            kwargs["directed_city_pairs"] = {
                (start_city, target_city),
                (target_city, start_city),
            }
            if not cfg.RunUsePlannerBook.value:
                kwargs["max_restock"] = int(cfg.RunOutboundBook.value or 0) + int(
                    cfg.RunReturnBook.value or 0
                )
                kwargs["max_book_by_city"] = {
                    start_city: int(cfg.RunOutboundBook.value or 0),
                    target_city: int(cfg.RunReturnBook.value or 0),
                }
            if not cfg.RunUsePlannerHaggle.value:
                kwargs["auto_haggle"] = False
                kwargs["haggle_by_city"] = {
                    start_city: int(cfg.RunOutboundHaggleNum.value or 0),
                    target_city: int(cfg.RunReturnHaggleNum.value or 0),
                }
        else:
            selected_cities = self._selected_cities()
            if selected_cities:
                kwargs["include_cities"] = selected_cities
        return kwargs

    def _summary_text(self, summary: dict | None) -> str:
        if not summary:
            return "没有路线摘要"
        legs = summary.get("legs") or []
        if not legs:
            return "没有路线明细"
        parts = [self._summary_route_overview(summary)]
        for leg in legs:
            parts.append(self._summary_leg_text(leg))
        return "\n".join(parts)

    def _summary_leg_detail_text(self, summary: dict | None) -> str:
        legs = (summary or {}).get("legs") or []
        if not legs:
            return "没有路线明细"
        return "\n".join(self._summary_leg_text(leg) for leg in legs)

    def _summary_profit_text(self, summary: dict | None) -> str:
        if not summary:
            return "利润 -"
        jiaozi_profit = summary.get("jiaozi_profit")
        tiemeng_profit = summary.get("tiemeng_profit")
        if jiaozi_profit is not None and tiemeng_profit is not None:
            return f"利润 交子{jiaozi_profit}/铁盟币{tiemeng_profit}"
        total_profit = summary.get("total_profit")
        if total_profit is None:
            total_profit = summary.get("profit")
        return f"利润 {total_profit if total_profit is not None else '-'}"

    def _summary_route_overview(self, summary: dict | None) -> str:
        legs = (summary or {}).get("legs") or []
        fatigue = (summary or {}).get("tired")
        restock = (summary or {}).get("restock")
        parts = [self._summary_route_text(summary), self._summary_profit_text(summary)]
        if restock is not None:
            parts.append(f"共{restock}书")
        if fatigue is not None:
            parts.append(f"总疲劳{fatigue}")
        if len(legs) == 2:
            parts.append(
                f"书量 {legs[0].get('restock', 0)}+{legs[1].get('restock', 0)}"
            )
        return "，".join(parts)

    def _summary_leg_text(self, leg: dict) -> str:
        haggle_num = int(leg.get("haggle_num") or 0)
        haggle = f"抬砍{min(20, haggle_num)}%" if haggle_num > 0 else "不抬砍"
        return (
            f"{leg.get('buy_city')} -> {leg.get('sell_city')}："
            f"{leg.get('restock', 0)}书，{haggle}，"
            f"疲劳{leg.get('tired', '-')}"
        )

    def _summary_route_text(self, summary: dict | None) -> str:
        legs = (summary or {}).get("legs") or []
        if not legs:
            return "未知路线"
        buy_city = str(legs[0].get("buy_city") or "")
        sell_city = str(legs[0].get("sell_city") or "")
        if buy_city and sell_city:
            return f"{buy_city} <-> {sell_city}"
        return buy_city or sell_city or "未知路线"

    def _candidate_text(self, summary: dict | None) -> str:
        if not summary:
            return "没有路线摘要"
        profit_text = format_profit_status(summary)
        lines = [self._summary_route_overview(summary)]
        if profit_text:
            lines.append(profit_text.replace("\n", "  "))
        leg_text = " | ".join(self._summary_leg_text(leg) for leg in (summary.get("legs") or [])[:2])
        if leg_text:
            lines.append(leg_text)
        return "\n".join(lines)

    def _candidate_title(self, index: int, summary: dict | None, selected: bool) -> str:
        title = f"候选路线 {index + 1}"
        if summary:
            reference_profit = summary.get("reference_profit")
            if reference_profit is None:
                reference_profit = summary.get("general_profit_index")
            if reference_profit is not None:
                label = str(summary.get("reference_profit_label") or "综合参考利润")
                title += f" {label}{reference_profit}"
        if selected:
            title += "（已选择）"
        return title

    def _show_route_candidates(self, *, scroll_to_candidates: bool = False):
        show_candidates = self._candidate_count() > 1
        for index, card in enumerate(self.routeCandidateCards):
            if not show_candidates or index >= len(self.plannedRouteOptions):
                card.hide()
                continue
            _, summary = self.plannedRouteOptions[index]
            selected = index == self.selectedRouteIndex
            card.titleLabel.setText(self._candidate_title(index, summary, selected))
            card.contentLabel.setText(self._candidate_text(summary))
            card.show()
            button = self.routeCandidateButtons[index]
            button.setText("已选" if selected else "选择")
            button.setEnabled(not selected)
        self._rebuildLayout()
        if show_candidates and scroll_to_candidates:
            QTimer.singleShot(0, self._scroll_to_config_top)

    def selectRouteCandidate(self, index: int, *, scroll_to_candidates: bool = False):
        if index < 0 or index >= len(self.plannedRouteOptions):
            return
        self.selectedRouteIndex = index
        self.plannedRoute, self.plannedSummary = self.plannedRouteOptions[index]
        self._show_route_candidates(scroll_to_candidates=scroll_to_candidates)
        from auto.run_business.status_fields import summary_profit_status_fields

        status = {
            "stage": f"已选择候选路线 {index + 1}",
            "detail": self._summary_leg_detail_text(self.plannedSummary),
            "route": self._summary_route_text(self.plannedSummary),
        }
        status.update(summary_profit_status_fields(self.plannedSummary))
        self.updateRunStatus(status)

    def ensureAccountConfigReady(self) -> bool:
        if not account_config_auto_enabled():
            return True
        reasons = missing_account_config_reasons()
        if not reasons:
            return True

        self.pendingRunAfterPlan = False
        self.runActionButton.setEnabled(True)
        self.runActionButton.setText("执行")
        self.stopRunButton.setEnabled(False)

        detail = "；".join(reasons)
        self.updateRunStatus({"stage": "需要读取账号配置", "detail": detail})
        w = MessageBox(
            "需要读取账号配置",
            "当前为账号配置自动读取模式，但货舱或主城声望配置不完整。\n\n"
            f"{detail}\n\n"
            "请先读取账号配置后再规划或执行跑商。",
            self,
        )
        w.yesButton.setText("读取配置")
        w.cancelButton.setText("稍后")
        if w.exec():
            QTimer.singleShot(120, self.focusAndAnalyzeAccountProfile)
        return False

    def planBusiness(self, execute_after_plan: bool = False):
        from auto.run_business import select_planned_routes

        if self.planWorker and self.planWorker.isRunning():
            if execute_after_plan:
                self.pendingRunAfterPlan = True
                self.runActionButton.setEnabled(False)
                self.runActionButton.setText("规划中")
                self.updateRunStatus({"stage": "等待规划完成", "detail": "路线规划完成后将自动执行"})
            return
        if not self.ensureAccountConfigReady():
            return
        if self._city_selection_mode() == "manual" and not self._manual_route_cities():
            self.updateRunStatus(
                {"stage": "手动城市未完成", "detail": "起始城市和目标城市不能相同"}
            )
            InfoBar.warning(
                title="",
                content="请分别选择起始城市和目标城市。",
                orient=Qt.Orientation.Horizontal,
                isClosable=False,
                parent=self,
            )
            return
        self._clear_planned_route()
        self.pendingRunAfterPlan = execute_after_plan
        self.updateRunStatus({"stage": "正在规划路线", "detail": "正在读取行情并计算推荐路线"})
        self.planBusinessCard.loading(True)
        self.planWorker = Worker(
            select_planned_routes,
            lambda: None,
            top_n=self._candidate_count(),
            **self._planner_kwargs(),
        )
        self.planWorker.result.connect(self.on_plan_result)
        self.planWorker.finished.connect(
            lambda: self.on_plan_worker_finished(self.planWorker)
        )
        self.planWorker.start()

    def analyzeAccountProfile(self):
        from auto.run_business.account_profile import analyze_account_profile

        if not account_config_auto_enabled():
            self.updateRunStatus(
                {
                    "stage": "账号配置手动模式",
                    "detail": "手动模式不会自动读取或写入账号配置",
                }
            )
            InfoBar.warning(
                title="",
                content="当前为手动模式，请在规划参数中手动维护账号配置。",
                orient=Qt.Orientation.Horizontal,
                isClosable=False,
                parent=self,
            )
            return
        if self.accountProfileWorker and self.accountProfileWorker.isRunning():
            self.updateRunStatus({"stage": "正在读取账号配置", "detail": "账号配置读取已经在运行中"})
            return
        self.updateRunStatus({"stage": "正在读取账号配置", "detail": "正在读取货舱和城市声望"})
        self.accountConfigModeComboBox.setEnabled(False)
        self.accountProfileWorker = Worker(analyze_account_profile, lambda: None)
        self.accountProfileWorker.result.connect(self.on_account_profile_result)
        self.accountProfileWorker.finished.connect(
            lambda: self.on_account_profile_finished(self.accountProfileWorker)
        )
        self.accountProfileWorker.start()

    def focusAndAnalyzeAccountProfile(self):
        self.updateRunStatus({"stage": "准备读取账号配置", "detail": "正在定位账号配置读取选项"})
        QTimer.singleShot(120, self._scrollToAccountProfileAndAnalyze)

    def _scrollToAccountProfileAndAnalyze(self):
        self.ensureWidgetVisible(self.accountConfigModeCard, 36, 36)
        QTimer.singleShot(120, self.analyzeAccountProfile)

    def on_account_profile_result(self, result):
        if not result.ok:
            logger.warning(result.error or "账号配置读取失败")
            self.updateRunStatus(
                {"stage": "账号配置读取失败", "detail": result.error or "请检查当前游戏页面后重试"}
            )
            InfoBar.warning(
                title="",
                content=result.error or "账号配置读取失败",
                orient=Qt.Orientation.Horizontal,
                isClosable=False,
                parent=self,
            )
            return
        from auto.run_business.config_updates import update_trade_account_profile

        updates = update_trade_account_profile(
            cargo_capacity=result.cargo_capacity,
            prestige_by_city=result.prestige_by_city,
            unavailable_cities=result.unavailable_cities,
            reason="界面读取账号配置",
        )
        if result.cargo_capacity is not None:
            self.plannerMaxLotCard.spinBox.setValue(cfg.tradePlannerMaxLot.value)
        self.prestigeByCityCard.textEdit.setPlainText(
            self.prestigeByCityCard._format(cfg.tradePlannerPrestigeByCity.value or {})
        )
        self._clear_planned_route()
        self._update_city_checkbox_state()
        detail = "，".join(updates) if updates else "未识别到可更新的账号配置"
        self.updateRunStatus({"stage": "账号配置读取完成", "detail": detail})
        InfoBar.success(
            title="",
            content="账号配置已更新: " + detail,
            orient=Qt.Orientation.Horizontal,
            isClosable=False,
            parent=self,
        )

    def on_account_profile_finished(self, worker: Optional[Worker]):
        self.accountConfigModeComboBox.setEnabled(True)
        if worker:
            worker.deleteLater()
        self.accountProfileWorker = None

    def on_plan_result(self, result):
        candidates, error = result
        if error:
            logger.warning(error)
            self.pendingRunAfterPlan = False
            self.runActionButton.setEnabled(True)
            self.runActionButton.setText("执行")
            self.stopRunButton.setEnabled(False)
            self.updateRunStatus({"stage": "规划失败", "detail": error})
            InfoBar.warning(
                title="",
                content=error,
                orient=Qt.Orientation.Horizontal,
                isClosable=False,
                parent=self,
            )
            return
        self.plannedRouteOptions = candidates[: self._candidate_count()]
        self.selectedRouteIndex = -1
        self.selectRouteCandidate(0, scroll_to_candidates=self._candidate_count() > 1)
        logger.info(
            "自动规划候选路线:\n"
            + "\n\n".join(
                f"候选路线 {index + 1}\n{self._summary_text(summary)}"
                for index, (_, summary) in enumerate(self.plannedRouteOptions)
            )
        )
        if self.pendingRunAfterPlan:
            self.pendingRunAfterPlan = False
            self.runActionButton.setEnabled(True)
            self.runActionButton.setText("执行")
            self.stopRunButton.setEnabled(False)
            content = (
                "已完成规划，请选择路线后点击执行"
                if self._candidate_count() > 1
                else "已完成规划，已选择最优路线，请点击执行"
            )
            InfoBar.success(
                title="",
                content=content,
                orient=Qt.Orientation.Horizontal,
                isClosable=False,
                parent=self,
            )
        else:
            content = (
                f"自动规划完成，已展示前 {len(self.plannedRouteOptions)} 条候选路线"
                if self._candidate_count() > 1
                else "自动规划完成，已选择最优路线"
            )
            InfoBar.success(
                title="",
                content=content,
                orient=Qt.Orientation.Horizontal,
                isClosable=False,
                parent=self,
            )

    def on_plan_worker_finished(self, worker: Optional[Worker]):
        self.planBusinessCard.loading(False)
        if self.pendingRunAfterPlan and not self.plannedRouteOptions:
            self.pendingRunAfterPlan = False
            self.runActionButton.setEnabled(True)
            self.runActionButton.setText("执行")
            self.stopRunButton.setEnabled(False)
        if worker:
            worker.deleteLater()
        self.planWorker = None

    def runPlannedBusiness(self):
        if self.plannedRunWorker and self.plannedRunWorker.isRunning():
            self.updateRunStatus({"stage": "正在运行", "detail": "自动跑商已经在运行中"})
            return
        if not self.ensureAccountConfigReady():
            return
        if not self.plannedRoute:
            self.updateRunStatus(
                {
                    "stage": "需要先规划路线",
                    "detail": "当前没有可执行路线，正在自动规划候选路线",
                }
            )
            InfoBar.warning(
                title="",
                content=(
                    "当前还没有规划路线，已自动开始规划；规划后请选择路线再执行"
                    if self._candidate_count() > 1
                    else "当前还没有规划路线，已自动开始规划最优路线"
                ),
                orient=Qt.Orientation.Horizontal,
                isClosable=False,
                parent=self,
            )
            self.runActionButton.setEnabled(False)
            self.runActionButton.setText("规划中")
            self.stopRunButton.setEnabled(False)
            self.planBusiness(execute_after_plan=True)
            return
        self._start_planned_route_run()

    def _start_planned_route_run(self):
        from auto.run_business import execute_planned_route, stop

        if self.plannedRunWorker and self.plannedRunWorker.isRunning():
            return
        if not self.ensureAccountConfigReady():
            return
        if not self.plannedRoute:
            self.runPlannedBusiness()
            return
        self.updateRunStatus({"stage": "准备执行自动跑商", "detail": "正在按已规划路线启动"})
        self.runActionButton.setEnabled(False)
        self.runActionButton.setText("执行中")
        self.stopRunButton.setEnabled(True)
        self.stopRunButton.setText("停止")
        self.plannedRunWorker = Worker(
            execute_planned_route,
            stop,
            route=self.plannedRoute,
            summary=self.plannedSummary,
        )
        self.plannedRunWorker.result.connect(self.on_planned_run_result)
        self.plannedRunWorker.finished.connect(
            lambda: self.on_planned_run_finished(self.plannedRunWorker)
        )
        self.plannedRunWorker.start()

    def on_planned_run_result(self, result):
        from auto.run_business.status_fields import summary_profit_status_fields

        if not result.ok:
            logger.warning(result.error or "自动规划跑商失败")
            self.updateRunStatus(
                {"stage": "跑商失败", "detail": result.error or "自动规划跑商失败"}
            )
            return
        status = {
            "stage": "跑商完成" if result.executed else "规划完成",
            "detail": "自动跑商流程已结束" if result.executed else "路线已规划完成",
        }
        status.update(summary_profit_status_fields(result.summary))
        self.updateRunStatus(status)
        logger.info(f"自动规划跑商完成: executed={result.executed}")

    def on_planned_run_finished(self, worker: Optional[Worker]):
        self.runActionButton.setEnabled(True)
        self.runActionButton.setText("执行")
        self.stopRunButton.setEnabled(False)
        self.stopRunButton.setText("停止")
        if worker:
            worker.deleteLater()
        self.plannedRunWorker = None

    def _active_run_worker(self) -> Optional[Worker]:
        for worker in (self.plannedRunWorker,):
            if worker and worker.isRunning():
                return worker
        return None

    def stopRunning(self):
        from auto.run_business import stop

        worker = self._active_run_worker()
        stop()
        if worker:
            self.updateRunStatus({"stage": "正在停止", "detail": "已发送停止请求，当前步骤结束后会停止"})
            worker.stop()
            self.stopRunButton.setText("停止中")
            self.stopRunButton.setEnabled(False)
            InfoBar.success(
                title="",
                content="已发送停止请求，当前步骤结束后会停止",
                orient=Qt.Orientation.Horizontal,
                isClosable=False,
                parent=self,
            )
            return
        InfoBar.warning(
            title="",
            content="当前没有正在运行的跑商任务",
            orient=Qt.Orientation.Horizontal,
            isClosable=False,
            parent=self,
        )
