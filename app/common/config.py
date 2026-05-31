"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-04-02 19:13:20
LastEditTime: 2024-05-10 23:32:54
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

import sys

from qfluentwidgets import ConfigItem, QConfig, Theme, qconfig, ConfigSerializer

from app.utils.config import CITYS
from core.control.adb_port import EmulatorInfo, EmulatorType
from version import __version__


class RunningBusinessConfig(QConfig):
    """Config of application"""

    RunBook = ConfigItem("RunBuy", "Book", 0, None)
    RunOutboundBook = ConfigItem("RunBuy", "OutboundBook", 0, None)
    RunReturnBook = ConfigItem("RunBuy", "ReturnBook", 0, None)
    RunUsePlannerBook = ConfigItem("RunBuy", "UsePlannerBook", True, None)
    RunUsePlannerHaggle = ConfigItem("RunBuy", "UsePlannerHaggle", True, None)
    RunHaggleNum = ConfigItem("RunBuy", "HaggleNum", 0, None)
    RunOutboundHaggleNum = ConfigItem("RunBuy", "OutboundHaggleNum", 0, None)
    RunReturnHaggleNum = ConfigItem("RunBuy", "ReturnHaggleNum", 0, None)
    RunUseStrengthMedicine = ConfigItem("RunBuy", "UseStrengthMedicine", False, None)
    RunStrengthLollipopCount = ConfigItem("RunBuy", "StrengthLollipopCount", 0, None)
    RunStrengthLollipopUseAll = ConfigItem("RunBuy", "StrengthLollipopUseAll", False, None)
    RunStrengthGumCount = ConfigItem("RunBuy", "StrengthGumCount", 0, None)
    RunStrengthGumUseAll = ConfigItem("RunBuy", "StrengthGumUseAll", False, None)
    RunStrengthCactusCandyCount = ConfigItem("RunBuy", "StrengthCactusCandyCount", 0, None)
    RunStrengthCactusCandyUseAll = ConfigItem("RunBuy", "StrengthCactusCandyUseAll", False, None)
    RunAllowFood = ConfigItem("RunBuy", "AllowFood", False, None)
    RunUseHuashi = ConfigItem("RunBuy", "UseHuashi", False, None)
    RunHuashiCount = ConfigItem("RunBuy", "HuashiCount", 0, None)
    RunHuashiUseAll = ConfigItem("RunBuy", "HuashiUseAll", False, None)
    RunAllowDrink = ConfigItem("RunBuy", "AllowDrink", False, None)

    for city in CITYS:
        # 特殊适配7号自由港
        locals()[f"{city}进货书"] = ConfigItem(
            "CityBook", city.replace("七号自由港", "7号自由港"), 0, None
        )
        locals()[f"{city}议价次数"] = ConfigItem(
            "CityHaggle", city.replace("七号自由港", "7号自由港"), 0, None
        )


def isWin11():
    return sys.platform == "win32" and sys.getwindowsversion().build >= 22000

class EmulatorSerializer(ConfigSerializer):
    def serialize(self, value: EmulatorInfo) -> dict:
        return value.to_dict()

    def deserialize(self, data: dict) -> EmulatorInfo:
        return EmulatorInfo.from_dict(data)

class Config(RunningBusinessConfig):
    """Config of application"""

    emulatorType = ConfigItem("Global", "emulatorType", "Auto", None)
    device = ConfigItem(
        "Global",
        "device",
        EmulatorInfo(name="自定义端口", port=16384, path="", type=EmulatorType.CUSTOM, index=0),
        serializer=EmulatorSerializer(),
    )

    # Manifest based updater
    updateManifestUrl = ConfigItem("Global", "updateManifestUrl", "", None)
    tradePlannerApiUrl = ConfigItem("TradePlanner", "ApiUrl", "https://reso-online-ddos.soli-reso.com/get_server_trade/", None)
    tradePlannerAccountConfigMode = ConfigItem("TradePlanner", "AccountConfigMode", "auto", None)
    tradePlannerAccountProfileReady = ConfigItem("TradePlanner", "AccountProfileReady", False, None)
    tradePlannerCitySelectionMode = ConfigItem("TradePlanner", "CitySelectionMode", "auto", None)
    tradePlannerManualStartCity = ConfigItem("TradePlanner", "ManualStartCity", CITYS[0] if CITYS else "", None)
    tradePlannerManualTargetCity = ConfigItem("TradePlanner", "ManualTargetCity", CITYS[1] if len(CITYS) > 1 else (CITYS[0] if CITYS else ""), None)
    tradePlannerUnavailableCities = ConfigItem("TradePlanner", "UnavailableCities", [], None)
    tradePlannerCityMode = ConfigItem("TradePlanner", "CityMode", "all", None)
    tradePlannerMixedCurrencyPriority = ConfigItem("TradePlanner", "MixedCurrencyPriority", "total", None)
    tradePlannerCandidateMode = ConfigItem("TradePlanner", "CandidateMode", "best", None)
    tradePlannerConfigPath = ConfigItem("TradePlanner", "ConfigPath", "", None)
    tradePlannerMaxLot = ConfigItem("TradePlanner", "MaxLot", 1136, None)
    tradePlannerMaxRestock = ConfigItem("TradePlanner", "MaxRestock", 6, None)
    tradePlannerBargainPercent = ConfigItem("TradePlanner", "BargainPercent", 20, None)
    tradePlannerRaisePercent = ConfigItem("TradePlanner", "RaisePercent", 20, None)
    tradePlannerBargainFatigue = ConfigItem("TradePlanner", "BargainFatigue", 20, None)
    tradePlannerRaiseFatigue = ConfigItem("TradePlanner", "RaiseFatigue", 20, None)
    tradePlannerCompareNoReturnBargain = ConfigItem("TradePlanner", "CompareNoReturnBargain", True, None)
    tradePlannerDefaultPrestigeLevel = ConfigItem("TradePlanner", "DefaultPrestigeLevel", 20, None)
    tradePlannerPrestigeLevelThresholds = ConfigItem("TradePlanner", "PrestigeLevelThresholds", {}, None)
    tradePlannerPrestigeByCity = ConfigItem("TradePlanner", "PrestigeByCity", {}, None)
    tradePlannerRoleResonance = ConfigItem("TradePlanner", "RoleResonance", {}, None)
    tradePlannerUseDefaultRoles = ConfigItem("TradePlanner", "UseDefaultRoles", True, None)
    tradePlannerDisabledRoles = ConfigItem("TradePlanner", "DisabledRoles", [], None)
    tradePlannerProductUnlockStatus = ConfigItem("TradePlanner", "ProductUnlockStatus", {}, None)
    tradePlannerProductUnlockStatusByCity = ConfigItem("TradePlanner", "ProductUnlockStatusByCity", {}, None)
    tradePlannerBlockedGoods = ConfigItem("TradePlanner", "BlockedGoods", [], None)
    tradePlannerAllowedGoods = ConfigItem("TradePlanner", "AllowedGoods", [], None)
    tradePlannerEvents = ConfigItem("TradePlanner", "Events", {}, None)
    tradePlannerIncludeCities = ConfigItem("TradePlanner", "IncludeCities", [], None)
    tradePlannerExcludeCities = ConfigItem("TradePlanner", "ExcludeCities", [], None)
    tradePlannerAllowedCityPairs = ConfigItem("TradePlanner", "AllowedCityPairs", [], None)
    tradePlannerBlockedCityPairs = ConfigItem("TradePlanner", "BlockedCityPairs", [], None)


YEAR = 2023
AUTHOR = "DaiMao204"
VERSION = __version__
REPO_URL = "https://github.com/DaiMao204/NightChainsTech"


cfg = Config()
cfg.themeMode.value = Theme.AUTO
qconfig.load("config/app.json", cfg)
