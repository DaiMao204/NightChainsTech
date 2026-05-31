"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-04-08 17:45:06
LastEditTime: 2024-09-10 20:22:52
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

from pathlib import Path
from typing import Dict, List

from pydantic import BaseModel, Field

from core.control.adb_port import EmulatorInfo, EmulatorType
from core.utils.utils import RESOURCES_PATH, read_json

ROOT_PATH = Path().resolve()
"""项目根目录路径"""
APP_PATH = ROOT_PATH / "config" / "app.json"
"""自动程序配置文件路径"""
APP_PATH.parent.mkdir(parents=True, exist_ok=True)
city_sell_data: Dict[str, Dict[str, int]] = read_json(
    RESOURCES_PATH / "goods/CityGoodsSellData.json"
)
CITYS = list(city_sell_data.keys())


class GlobalModel(BaseModel):
    """全局模型"""

    device: EmulatorInfo = EmulatorInfo(
        name="自定义端口", port=16384, path="", type=EmulatorType.CUSTOM, index=0
    )
    updateManifestUrl: str = ""
    """更新清单地址"""


class RunBuyModel(BaseModel):
    """进货"""

    Book: int = 0
    """固定进货书数量"""
    OutboundBook: int = 0
    """去程固定进货书数量"""
    ReturnBook: int = 0
    """回程固定进货书数量"""
    UsePlannerBook: bool = True
    """是否使用规划器推荐进货书数量"""
    UsePlannerHaggle: bool = True
    """是否使用规划器推荐议价幅度"""
    HaggleNum: int = 0
    """全局议价幅度百分比"""
    OutboundHaggleNum: int = 0
    """去程固定议价幅度百分比"""
    ReturnHaggleNum: int = 0
    """回程固定议价幅度百分比"""
    UseStrengthMedicine: bool = False
    """是否使用体力药"""
    StrengthLollipopCount: int = 0
    StrengthLollipopUseAll: bool = False
    StrengthGumCount: int = 0
    StrengthGumUseAll: bool = False
    StrengthCactusCandyCount: int = 0
    StrengthCactusCandyUseAll: bool = False
    AllowFood: bool = False
    """是否允许体力不足时优先吃便当"""
    UseHuashi: bool = False
    HuashiCount: int = 0
    HuashiUseAll: bool = False
    AllowDrink: bool = False
    """是否允许在主城喝酒恢复疲劳"""


class TradePlannerModel(BaseModel):
    """Trade route planner options."""

    ApiUrl: str = "https://reso-online-ddos.soli-reso.com/get_server_trade/"
    AccountConfigMode: str = "auto"
    AccountProfileReady: bool = False
    CitySelectionMode: str = "auto"
    ManualStartCity: str = CITYS[0] if CITYS else ""
    ManualTargetCity: str = CITYS[1] if len(CITYS) > 1 else (CITYS[0] if CITYS else "")
    UnavailableCities: List[str] = Field(default_factory=list)
    CityMode: str = "all"
    MixedCurrencyPriority: str = "total"
    CandidateMode: str = "best"
    ConfigPath: str = ""
    MaxLot: int = 1136
    MaxRestock: int = 6
    BargainPercent: int = 20
    RaisePercent: int = 20
    BargainFatigue: int = 20
    RaiseFatigue: int = 20
    CompareNoReturnBargain: bool = True
    DefaultPrestigeLevel: int = 20
    PrestigeLevelThresholds: dict = Field(default_factory=dict)
    PrestigeByCity: dict = Field(default_factory=dict)
    RoleResonance: dict = Field(default_factory=dict)
    UseDefaultRoles: bool = True
    DisabledRoles: List[str] = Field(default_factory=list)
    ProductUnlockStatus: dict = Field(default_factory=dict)
    ProductUnlockStatusByCity: dict = Field(default_factory=dict)
    BlockedGoods: List[str] = Field(default_factory=list)
    AllowedGoods: List[str] = Field(default_factory=list)
    Events: dict = Field(default_factory=dict)
    IncludeCities: List[str] = Field(default_factory=list)
    ExcludeCities: List[str] = Field(default_factory=list)
    AllowedCityPairs: List[str] = Field(default_factory=list)
    BlockedCityPairs: List[str] = Field(default_factory=list)


class Config(BaseModel):
    """自动程序配置"""

    Global: GlobalModel = GlobalModel()
    """全局"""
    CityBook: dict = Field(default_factory=lambda: {city: 0 for city in CITYS})
    """进货书"""
    CityHaggle: dict = Field(default_factory=lambda: {city: 0 for city in CITYS})
    """议价"""
    RunBuy: RunBuyModel = RunBuyModel()
    TradePlanner: TradePlannerModel = TradePlannerModel()
    """跑商配置"""


if APP_PATH.exists() and APP_PATH.is_file():
    data = read_json(APP_PATH)
    app = Config.model_validate(data)
