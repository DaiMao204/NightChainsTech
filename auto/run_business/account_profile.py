from __future__ import annotations

import base64
import re
import json
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any

import cv2
import numpy as np
from loguru import logger

from app.common.runtime_status import emit_run_status
from app.utils.config import CITYS
from auto.run_business.main import go_business
from core.control.control import connect, input_swipe, input_tap, screenshot_image
from core.image.ocr import predict
from core.preset import get_station, go_city, go_home
from core.preset.map_navigation import (
    MapNavigationError,
    open_station_map_from_home,
    select_station_on_map,
)
from core.preset.page_state import capture_page_state
from core.utils.runtime_state import capture_state, ocr_texts
from core.utils.utils import RESOURCES_PATH, read_json

CARGO_CROP_POS1 = (850, 360)
CARGO_CROP_POS2 = (1260, 445)
PROFILE_ENTRY_POINT = (120, 660)
PROFILE_ENTRY_POINTS = ((160, 660), (145, 650), PROFILE_ENTRY_POINT, (36, 682))
PROFILE_MORE_INFO_POINT = (390, 317)
PROFILE_PRESTIGE_EYE_POINT = (362, 410)
PROFILE_PRESTIGE_DIALOG_CROP1 = (700, 245)
PROFILE_PRESTIGE_DIALOG_CROP2 = (1190, 675)
PROFILE_PRESTIGE_DIALOG_CONFIRM_POINT = (950, 645)
PROFILE_PRESTIGE_SCROLL_START = (960, 600)
PROFILE_PRESTIGE_SCROLL_END = (960, 325)
PROFILE_PRESTIGE_SCROLL_ATTEMPTS = 1
PROFILE_PANEL_CLOSE_POINT = (1020, 520)
PROFILE_PLAIN_CONFIRM_POINT = (640, 505)
PROFILE_PLAIN_CONFIRM_CROP1 = (300, 240)
PROFILE_PLAIN_CONFIRM_CROP2 = (980, 560)
PRESTIGE_THRESHOLDS_PATH = RESOURCES_PATH / "goods" / "CityPrestigeThresholds2026.json"
CITY_GOODS_PATH = RESOURCES_PATH / "goods" / "CityGoodsSellData.json"
ATTACHED_TO_CITY_PATH = RESOURCES_PATH / "goods" / "AttachedToCityData.json"
TRADE_DATA_PATH = RESOURCES_PATH / "goods" / "ColumbaTradeData2026.json"
ROLE_CATALOG_PATH = RESOURCES_PATH / "goods" / "RoleCatalog2026.json"
CREW_TIGHT_BADGE_TEMPLATE_PATH = RESOURCES_PATH / "goods" / "CrewTightBadgeTemplates2026.json"
CREW_AWAKE_ICON_TEMPLATE_PATH = RESOURCES_PATH / "goods" / "CrewAwakeIconTemplates2026.json"
CREW_DEBUG_DIR = RESOURCES_PATH.parent / "diagnostics" / "crew_resonance"
PLANNER_MAX_PRESTIGE_LEVEL = 20
PROFILE_PANEL_TEXTS = ("查看更多信息", "运营总览", "导航手册", "UID", "资产")
PROFILE_PLAIN_CONFIRM_TEXTS = ("确认", "确定")
CREW_WAREHOUSE_ENTRY_POINTS = ((1225, 58), (1210, 58), (1190, 58), (1240, 84))
CREW_WAREHOUSE_TEXTS = ("乘员仓库", "获取时间", "共振", "等级", "筛选")
CREW_SORT_TEXTS = ("获取时间",)
CREW_LIST_CROP1 = (0, 80)
CREW_LIST_CROP2 = (1260, 695)
CREW_SCROLL_START = (920, 620)
CREW_SCROLL_END = (920, 455)
CREW_SAFE_NAME_Y_MIN = 280
CREW_SAFE_NAME_Y_MAX = 690
CREW_SCROLL_ATTEMPTS = 42
CREW_SCROLL_STALE_LIMIT = 3
CREW_PAGE_SETTLE_SECONDS = 0.65
CREW_RETRY_SETTLE_SECONDS = 0.55
CREW_SCROLL_TIME_MS = 1250
CREW_AFTER_SCROLL_SECONDS = 1.65
ROLE_RESONANCE_LEVELS = {0, 1, 2, 3, 4, 5}
PLANNER_ROLE_RESONANCE_LEVELS = {0, 1, 4, 5}
ROLE_OCR_EQUIVALENTS = str.maketrans(
    {
        "鬃": "繁",
        "繁": "繁",
        "魔": "魇",
        "剎": "刹",
        "拉": "菈",
        "聯": "咲",
        "联": "咲",
        "唉": "咲",
        "集": "隼",
        "駒": "驹",
        "·": "",
        "・": "",
        " ": "",
    }
)
ROLE_OCR_ALIASES = {
    "拉姐": "拉妲",
    "狮": "狮鬃",
}
CREW_NAME_EXCLUDE_KEYWORDS = (
    "乘员",
    "仓库",
    "获取",
    "时间",
    "筛选",
    "等级",
    "共振",
    "排序",
    "全部",
    "Lv",
    "LV",
)
CREW_BADGE_TEMPLATE_SIZE = (64, 64)
CREW_RIGHT_BADGE_TEMPLATE_SIZE = (48, 80)
CREW_TIGHT_RIGHT_BADGE_TEMPLATE_SIZE = (42, 80)
CREW_BADGE_TEMPLATE_MATCH_MIN = 0.73
CREW_BADGE_TEMPLATE_MATCH_MARGIN = 0.06
CREW_BADGE_MIN_LABEL_PIXELS = 120
CREW_BADGE_MIN_DIGIT_PIXELS = 220
CREW_CARD_BASE_LEFTS = (16, 195, 375, 555, 735, 914, 1094)
CREW_CARD_BASE_WIDTH = 168
CREW_CARD_NAME_ROW_TO_TOP = 230
CREW_CARD_FULL_BADGE_FROM_RIGHT = (-78, -2)
CREW_CARD_TIGHT_BADGE_FROM_RIGHT = (-48, 6)
CREW_CARD_FULL_BADGE_FROM_ROW_Y = (-250, -128)
CREW_CARD_TIGHT_BADGE_FROM_ROW_Y = (-250, -150)
CREW_CARD_MIN_BADGE_SCORE = 0.58
CREW_CARD_MIN_BADGE_MARGIN = 0.045
CREW_CARD_RARITY_STRIPE_FROM_BOTTOM = (42, 5)
CREW_AWAKE_TEMPLATE_MATCH_MIN = 0.74
CREW_AWAKE_TEMPLATE_MATCH_MARGIN = 0.012
CREW_AWAKE_TEMPLATE_STRONG_MIN = 0.84
CREW_AWAKE_TEMPLATE_SCALES = (
    0.52,
    0.58,
    0.64,
    0.70,
    0.76,
    0.82,
    0.88,
    0.94,
    1.00,
    1.08,
    1.16,
    1.24,
    1.32,
    1.40,
    1.50,
)
_CREW_BADGE_TEMPLATES: dict[int, list[np.ndarray]] = {}
_CREW_RECOGNITION_DEBUG_RECORDS: dict[str, dict[str, Any]] = {}
_CREW_RECOGNITION_DEBUG_RUN_ID = ""
_CREW_RIGHT_BADGE_TEMPLATE_DATA = {
    4: (
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/8AAAAAB/8AAAAAD/8AAAAAD/8AAAAAH/8AAAAAP/8AAAAAP/8AAAAAf/8AAAAA//8AAAAA//8AAAAAAAAAAAAAAAAAAAO2djI6AAPmfzPiAAOyfzfjAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAPAAAAAAAfgAAAAAAfgAAAAAAfgAAAAAAfgAAAAAAHgAAAAAADgAAAAAAfgAAAAAAPgAAAAAAPAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAAAACAAAAAAABgAAAAAAfgAAAAAAAAAAAAAAAA"
    ),
    5: (
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD///AAAAD///gAAAD///gAAAD///gAAAD///gAAAH///gAAAH///gAAAH///AAAAH+AAAAAAH+AAAAAAH8AAAAAAAAAAAAAAAAAAAAAHZmwldgAHbP9nxgAHZL9nxgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABAAAAAAABwAAAAA"
    ),
}
_CREW_TIGHT_RIGHT_BADGE_TEMPLATE_DATA = {
    4: (
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//gAAAA//gAAAA//wAAAA//wAAAA//gAAAA//+AAAA///gAAA///gAAA///gAAA///gAAA///gAAA///gAAA///gAAA///AAAAAAAAAAAzAQmYAA/+7v4AAn/784AQ//784AQ////4AwjAAGYB4AAAAAB8///+AB8///+AB8///+AD8///+AD8///+AD8AH/gAD8AD/AAD8AD/AAD8AD/AAD+AAAAAD+gAAAAD+gAAAAD+gAAAAH+gAAAAH+gAAAAH+gAAAAH+wAAAAH+wAAAAH/wAAAAH/wAAAAH/wAAAAH/wAAAAH/wAAAAH/wAAAAH/4AAAAH/4AAAAP/4AAAAP/4AAAAP/4AAAAP/4AAAAP/8AAAAP/8AAAAP/8AAAAP/8AAAAP/8AAAAP/+AAAAP/+AAAAP/+AAAAP/+AAAAP//AAAAP//AAAAP//AAAAP/",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP+AAAAAf/AAAAA//AAAAB//AAAAD//AAAAD//AAAgH//AABwP//AABwf//AAB4f//AAB4AAAAAB4mAgOwB4//3vwD4v/34wD4///4wD4////wD8mAAEwD8AAAAAH8///+AH8///+AH8///+AH8///+AH8///+AH8AP/gAH8AH/AAH8AH/AAH8AH/AAH+AAAAAH+AAAAAP+AAAAAP+AAAAAP+AAAAAP+AAAAAP+AAAAAP+AAAAAP+AAAAAP+AAAAAP/AAAAAP/AAAAAP/AAAAAP/AAAAAP/AAAAAP/AAAAAP/AAAAAP/AAAAAP/AAAAAP/AAAAAP/AAAAAP/AAAAAP/AAAAAP/AAAAAP/AAAAAf/AAAAAf/AAAAAf/AAAAAf/AAAAAf/AAAAAf/",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH/AAAAAf/gAAAAf/gAAAA//gAAAB//gAAAD//gAAAD//gAAAH//gAAAP//gAAAP//gAAAAAAAAAMzAQGYA93+7/4A9n+784A8/+784A9//7/4AMjAIGYAAAAAAAAf///+AAf///+AAf///+AAf///+AAf///+ABAAH/gABAAD/AABAAD/AABAAD/AABAAAAAABAAAAAADAAAAAADAAAAAADAAAAAADAAAAAADAAAAAADAAAAAADAAAAAADAAAAAAHAAAAAAHAAAAAAHwAAAAAH4AAAAAH4AAAAAH4AAAAAH4AAAAAHYAAAAAHwAAAAAHgAAAAAHAAAAAAPAAAAAAPAAAAAAPAAAAAAPAAAAAAPAOAAAAPIPwAAAPfD+AAAPP/DwAAPD/+HwAPAP//4APAAf//8PAAD////",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH+AAAAAf/gAAAA//gAAAA//gAAAB//gAAAD//gAAAH//gAAAH//gAAAP//gAAAf//AAAAAAAAAANiAQGQA9/8z/wBdn+78wBZ///8wBZ////wBMiAIGYDAAAAAADf///+ADf///+ADf///+ADf///+ADf///+ADAAH/gADAAD/AADAAD/AADAAD/AADAAAAAAHAAAAAAHAAAAAAHAAAAAAHAAAAAAHAAAAAAHAAAAAAHAAAAAAHAAAAAAHAAAAAAPAAAAAAPAAAAAAPAAAAAAPAAAAAAPAAAAAAPAAAAAAPAAAAAAPAAAAAAPAAAAAAPAAAAAAPAAAAAAPAAAAAAP4AAAAAP/gAAAAP/+AAAAP//gAAAP//4AAAP///AAAP///gAAP///gAAP///wAAP///gAAP",
    ),
    5: (
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAD/AAAAAD/AAAAAD/ABx4AD/AAMAAD//8AAAD8//AAAD4//AAAD4//AAADw/+AAABg/+AAAAA/+AGAAA//4CAAAAD+CAAQAH+CAAAAH8KAAAAD+AAAAzf/AAAg3f+AABg3/nAABg3/+AABh39/ACBDAAAAGBDB/gAHBDD/gAHABD/gAHCAP/gAPCA//AOPCc//AePi+/+AePi//4A+Pj//gA+fjf8ADufj/AADmfg/AADmfgfAADufgfAADOfgPAAGOfwPAAcOfwPAA4OfwPABwOfwHADgOfwHAHAOfwDAOAGfwDA8AG/wDDgAG/wBHAAG/wBOAAG/wAcAAC/wA4AAA/wAwAAA/wAgAAA/4AAAAA/4AAAAA/4AAAAC/6AAA///6AAA/5/7gABwB/75ABgB/7/AAAB/7/AAAB/7/AAAB/7/AAAB/7/AAAB/7/AwAB/7/",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//+AAAA///gAAA///wAAA///8AAA///+AAA////wAA////4AA////8AA////8AA////+AA////+AA/////AA/////AA//AB/AAz/AD/AAj/AAOAAAAAQWIA/3+b/8A93/7/4A8//784A8////4A////38AgAAAAAA4AcP8AA88cf+AA/+If+AA////8AA////8AA////4AA////wAA////gAA///+AAA///wAAA//wAAAA4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB///wAAD///wAAD///wAAD///wAAD///wAAD///wAAD///wAAD/AAAAAD+AAAAAD+AAAAAD+AAAAAAAAAAAA//+z/wA5v+z8wAZ//74wAZ//7/wAd3HKmwAAAAAAAAAAAf8AAAwAf8AAD8A/8AAH/j/4AAP///4AAH///wAAD///gAAB//+AAAAP/4AAAAAcAAAAAAAAAAAAAAAAAAgAAAAAAgAAAAAAwAAAAAA4AAAAAB4AAAAAB4AAAAAB8AAAAAD8AAAAAD+AAAAAD/AAAAAD/wAAAAD/4AAAAD/8AAAAH/+AAAAH//AAAAH//gAAAHP/wAAAHH/4AAAHj/8AAAHn/+AAAHg///wAH+P///+H//////3//////3//////3//////3////////////////////////////",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA//////g//////g//////g//////g//////g//////g//////g////9/g////5/g////5/g////5/g////x/g////w/g//HwA/g//AAAAAz+AAAAAMgAACYA//+7/4A9/+7/4A8//78/g9/////g///v//gAAAAA/gAAAf//gA4Pf//gB+////gH/////g//////g//////g//////h//////h//////h//////h//////j//////D/////8D/////gD////+AD////4AD////wAD////D/j///8f/j///5//z//////z//////z//////3//////3//////n//////n//////n//////n//////3//////3//////3//////3//////3//////3//////n//////n//////n//////n//////v//////v//////v",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/////wA/////wA/////wA/////wA/////wA/////wA/////wA/////wA/////wA/////wA/////wA/////wA/P///wA/P///wA/H///wAAD///wAn////wA/////wAv//9/wA///9/wA/////wA3/on/wAH+AN/wA/+f//ww/+///ww/////xw/////x4/////x4/////x4/////z4/////z4/////z8/////z8/////z8/////38/////38/////38/////38/////3+/////3+/////3+/////3+/////3+/////3+/////3+//////+//////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////",
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA///gAAA///gAAA///gAAA///gAAA///gAAA///gAAA///AAAA+AAAAAA8AAAAAA8AAAAAAAAAAAAAMAgMgAAv9v/gAAP/vxgAA///xgAAv///gAAEAAMgAAAAAAAAAAA/4AAAwA/4AAA4B/4AAA///wAAA///gAAA///gAAA//+AAAA//8AAAAP/gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAwAAAAAA8AAAAAC4AAAAAPwAAAAAfgAAAAA/IAAAAA/YAAAAB/WAAAAD/CAAAAD/gAAAAD/hAAAAD/lAAAED/wAAAAD/4AAAAD/cAAAAH/OAAAAH/HAAAAH/DgAAAH/BwAAAP/A4AAAP/AIAAAP/AAAAAP/ACAAAP/AHAAAP/AGAAAP/gGAAAP/wMAAAP/",
    ),
}


@dataclass
class AccountProfileResult:
    ok: bool
    city_name: str | None = None
    cargo_capacity: int | None = None
    prestige_by_city: dict[str, int] = field(default_factory=dict)
    prestige_value_by_city: dict[str, int] = field(default_factory=dict)
    role_resonance: dict[str, int] = field(default_factory=dict)
    unavailable_cities: list[str] | None = None
    error: str | None = None


@dataclass(frozen=True)
class CrewBadgePrediction:
    level: int
    confidence: float
    margin: float
    weight: int
    source: str


@dataclass(frozen=True)
class CrewAwakeIconTemplate:
    level: int
    scale: float
    gray: Any
    mask: Any


@dataclass
class CrewRoleCardCandidate:
    role: str
    text: str
    match_score: float
    name_x: float
    name_y: float
    row_y: float
    column_index: int
    card_rect: tuple[int, int, int, int]
    card_crop: Any
    visual_rarity: str | None
    catalog_rarity: str | None
    rarity: str | None
    allows_resonance_5: bool | None
    full_badge_rect: tuple[int, int, int, int]
    tight_badge_rect: tuple[int, int, int, int]
    search_badge_rect: tuple[int, int, int, int]
    full_badge_crop: Any
    tight_badge_crop: Any
    search_badge_crop: Any
    entry: dict[str, Any]


def _clean_text(text: str) -> str:
    return (
        str(text or "")
        .replace(" ", "")
        .replace(",", "")
        .replace("，", "")
        .replace("：", ":")
    )


def _numbers(text: str) -> list[int]:
    return [int(match.group(0)) for match in re.finditer(r"\d+", _clean_text(text))]


def _numbers_near_city(text: str, city: str) -> list[int]:
    return _numbers(_clean_text(text).replace(city, ""))


@lru_cache(maxsize=1)
def load_prestige_thresholds() -> dict[str, Any]:
    data = read_json(PRESTIGE_THRESHOLDS_PATH, {})
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def load_attached_to_city() -> dict[str, str]:
    data = read_json(ATTACHED_TO_CITY_PATH, {})
    if not isinstance(data, dict):
        return {}
    return {str(city): str(master) for city, master in data.items() if str(city).strip()}


def prestige_master_city(city_name: str | None) -> str | None:
    if not city_name:
        return None
    city = str(city_name)
    return load_attached_to_city().get(city, city)


@lru_cache(maxsize=1)
def load_city_names() -> tuple[str, ...]:
    thresholds = load_prestige_thresholds()
    cities = thresholds.get("cities") if isinstance(thresholds, dict) else {}
    names: set[str] = set()
    if isinstance(cities, dict):
        names.update(
            master
            for name in cities.keys()
            if (master := prestige_master_city(str(name).strip()))
        )

    if not names:
        city_goods = read_json(CITY_GOODS_PATH, {})
        if isinstance(city_goods, dict):
            names.update(str(name) for name in city_goods.keys() if str(name).strip())

    return tuple(sorted(names, key=len, reverse=True))


@lru_cache(maxsize=1)
def load_role_catalog_data() -> dict[str, Any]:
    data = read_json(ROLE_CATALOG_PATH, {})
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def load_role_catalog_names() -> tuple[str, ...]:
    data = load_role_catalog_data()
    raw_roles = data.get("roles") if isinstance(data, dict) else data
    if not isinstance(raw_roles, list):
        return load_configurable_role_names()

    roles: list[str] = []
    seen: set[str] = set()
    for name in raw_roles:
        role = str(name).strip()
        if not role or role in seen:
            continue
        seen.add(role)
        roles.append(role)
    return tuple(roles or load_configurable_role_names())


@lru_cache(maxsize=1)
def load_role_catalog_rarity() -> dict[str, str]:
    data = load_role_catalog_data()
    raw = data.get("rarity_by_role") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {
        str(role).strip(): str(rarity).strip()
        for role, rarity in raw.items()
        if str(role).strip() and str(rarity).strip()
    }


@lru_cache(maxsize=1)
def load_role_catalog_resonance_max() -> dict[str, int]:
    data = load_role_catalog_data()
    raw = data.get("resonance_max_by_role") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return {}
    result: dict[str, int] = {}
    for role, value in raw.items():
        role_name = str(role).strip()
        if not role_name:
            continue
        try:
            result[role_name] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def _role_catalog_rarity(role: str | None) -> str | None:
    if not role:
        return None
    return load_role_catalog_rarity().get(str(role).strip())


def _role_catalog_resonance_max(role: str | None) -> int | None:
    if not role:
        return None
    return load_role_catalog_resonance_max().get(str(role).strip())


@lru_cache(maxsize=1)
def load_configurable_role_names() -> tuple[str, ...]:
    data = read_json(TRADE_DATA_PATH, {})
    if not isinstance(data, dict):
        return ()

    roles: list[str] = []
    seen: set[str] = set()

    def add(names):
        for name in names or []:
            role = str(name).strip()
            if not role or role in seen:
                continue
            seen.add(role)
            roles.append(role)

    add((data.get("resonance_skills") or {}).keys())
    add((data.get("default_roles") or {}).keys())
    default_config = data.get("default_player_config") or {}
    add((default_config.get("roles") or {}).keys())
    return tuple(roles)


def _planner_role_level(level: int | None) -> int:
    try:
        value = int(level or 0)
    except (TypeError, ValueError):
        return 0
    if value in PLANNER_ROLE_RESONANCE_LEVELS:
        return value
    if value <= 0:
        return 0
    if value < 4:
        return 1
    return 5 if value >= 5 else 4


def _config_role_level(level: int | None, *, missing: int = 0) -> int:
    try:
        if level is None or level == "":
            return missing
        value = int(level)
    except (TypeError, ValueError):
        return missing
    if value in ROLE_RESONANCE_LEVELS:
        return value
    return 5 if value >= 5 else missing


def _threshold_map(city_name: str | None = None) -> dict[int, int]:
    thresholds = load_prestige_thresholds()
    cities = thresholds.get("cities") if isinstance(thresholds, dict) else {}
    raw: dict[str, Any] | None = None
    master_city = prestige_master_city(city_name)
    if master_city and isinstance(cities, dict):
        city_raw = cities.get(master_city)
        if isinstance(city_raw, dict) and len(city_raw) >= 3:
            raw = city_raw
    if raw is None:
        raw = thresholds.get("default") if isinstance(thresholds, dict) else {}
    if not isinstance(raw, dict):
        return {}
    result: dict[int, int] = {}
    for level, value in raw.items():
        try:
            result[int(level)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def prestige_value_to_level(
    prestige_value: int,
    city_name: str | None = None,
    *,
    max_level: int = PLANNER_MAX_PRESTIGE_LEVEL,
) -> int | None:
    """Convert raw city reputation value to the planner prestige level."""
    thresholds = _threshold_map(city_name)
    if not thresholds:
        return None

    level = 1
    for candidate_level, required_value in sorted(thresholds.items()):
        if candidate_level > max_level:
            continue
        if prestige_value >= required_value:
            level = candidate_level
        else:
            break
    return level


def parse_cargo_capacity(texts: list[str]) -> int | None:
    """Parse the max cargo number from OCR texts such as 13/545."""
    candidates: list[int] = []
    for text in texts:
        clean = _clean_text(text)
        for match in re.finditer(r"(\d+)\s*/\s*(\d+)", clean):
            candidates.append(int(match.group(2)))
    return max(candidates) if candidates else None


def parse_prestige_level(texts: list[str]) -> int | None:
    """Parse a direct city prestige level from OCR around the city page."""
    cleaned = [_clean_text(text) for text in texts if str(text).strip()]
    joined = "".join(cleaned)
    for pattern in (
        r"声望等级(?:Lv\.?|等级)?(\d{1,2})",
        r"声望(?:等级)?(?:Lv\.?)?(\d{1,2})",
    ):
        match = re.search(pattern, joined, re.I)
        if match:
            return max(1, min(int(match.group(1)), PLANNER_MAX_PRESTIGE_LEVEL))

    for index, text in enumerate(cleaned):
        if "声望" not in text:
            continue
        nearby = "".join(cleaned[index : index + 4])
        match = re.search(r"(?:Lv\.?)?(\d{1,2})", nearby, re.I)
        if match:
            return max(1, min(int(match.group(1)), PLANNER_MAX_PRESTIGE_LEVEL))
    return None


def _entry_center(entry: dict[str, Any]) -> tuple[float, float]:
    position = entry.get("position") or []
    if not position:
        return 0.0, 0.0
    xs = [float(point[0]) for point in position if len(point) >= 2]
    ys = [float(point[1]) for point in position if len(point) >= 2]
    if not xs or not ys:
        return 0.0, 0.0
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _entry_bounds(entry: dict[str, Any]) -> tuple[float, float, float, float]:
    position = entry.get("position") or []
    xs = [float(point[0]) for point in position if len(point) >= 2]
    ys = [float(point[1]) for point in position if len(point) >= 2]
    if not xs or not ys:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def _looks_like_prestige_value(value: int) -> bool:
    return 0 <= value <= 999999


def parse_city_prestige_values_from_entries(
    entries: list[dict[str, Any]],
    city_names: tuple[str, ...] | None = None,
) -> dict[str, int]:
    """Parse raw city reputation values from positioned OCR results."""
    city_names = city_names or load_city_names()
    cleaned_entries: list[tuple[str, float, float, dict[str, Any]]] = []
    for entry in entries:
        text = _clean_text(entry.get("text", ""))
        if not text:
            continue
        x, y = _entry_center(entry)
        cleaned_entries.append((text, x, y, entry))

    result: dict[str, int] = {}
    for city in city_names:
        city_entry = next(
            ((text, x, y, entry) for text, x, y, entry in cleaned_entries if city in text),
            None,
        )
        if city_entry is None:
            continue

        city_text, city_x, city_y, _ = city_entry
        candidates: list[int] = [
            value
            for value in _numbers_near_city(city_text, city)
            if _looks_like_prestige_value(value)
        ]
        for text, x, y, _ in cleaned_entries:
            if abs(y - city_y) > 36:
                continue
            if x < city_x - 20:
                continue
            candidates.extend(
                value for value in _numbers(text) if _looks_like_prestige_value(value)
            )
        if candidates:
            result[city] = max(candidates)

    return result


def parse_city_prestige_values(
    texts: list[str],
    city_names: tuple[str, ...] | None = None,
) -> dict[str, int]:
    """Fallback parser for OCR text-only results."""
    city_names = city_names or load_city_names()
    cleaned = [_clean_text(text) for text in texts if str(text).strip()]
    result: dict[str, int] = {}
    for city in city_names:
        for index, text in enumerate(cleaned):
            if city not in text:
                continue
            candidates: list[int] = []
            for piece in cleaned[index : index + 5]:
                if piece != text and any(
                    other_city != city and other_city in piece
                    for other_city in city_names
                ):
                    break
                candidates.extend(
                    value
                    for value in _numbers_near_city(piece, city)
                    if _looks_like_prestige_value(value)
                )
            if candidates:
                result[city] = max(candidates)
                break
    return result


def prestige_values_to_levels(values_by_city: dict[str, int]) -> dict[str, int]:
    levels: dict[str, int] = {}
    for city, prestige_value in values_by_city.items():
        level = prestige_value_to_level(prestige_value, city)
        if level is not None:
            levels[city] = level
    return levels


def _tap_ocr_text(
    texts: tuple[str, ...],
    *,
    fallback: tuple[int, int] | None = None,
    cropped_pos1: tuple[int, int] = (0, 0),
    cropped_pos2: tuple[int, int] = (0, 0),
) -> bool:
    raw = screenshot_image()
    for entry in predict(raw, cropped_pos1=cropped_pos1, cropped_pos2=cropped_pos2):
        entry_text = _clean_text(entry.get("text", ""))
        if not any(text in entry_text for text in texts):
            continue
        x, y = _entry_center(entry)
        input_tap((int(x), int(y)))
        return True
    if fallback:
        input_tap(fallback)
        return True
    return False


def _screen_texts(
    cropped_pos1: tuple[int, int] = (0, 0),
    cropped_pos2: tuple[int, int] = (0, 0),
) -> list[str]:
    raw = screenshot_image()
    return [
        _clean_text(entry.get("text", ""))
        for entry in predict(raw, cropped_pos1=cropped_pos1, cropped_pos2=cropped_pos2)
        if _clean_text(entry.get("text", ""))
    ]


def _has_any_text(texts: list[str], needles: tuple[str, ...]) -> bool:
    return any(needle in text for text in texts for needle in needles)


def _is_profile_panel_open() -> bool:
    return _has_any_text(_screen_texts(), PROFILE_PANEL_TEXTS)


def _is_crew_warehouse_open() -> bool:
    return _has_any_text(_screen_texts(), CREW_WAREHOUSE_TEXTS)


def _tap_plain_confirm_popup() -> bool:
    texts = _screen_texts(PROFILE_PLAIN_CONFIRM_CROP1, PROFILE_PLAIN_CONFIRM_CROP2)
    if not _has_any_text(texts, PROFILE_PLAIN_CONFIRM_TEXTS):
        return False
    input_tap(PROFILE_PLAIN_CONFIRM_POINT)
    time.sleep(1.0)
    return True


def _open_profile_panel() -> bool:
    go_home()
    time.sleep(0.5)
    for point in PROFILE_ENTRY_POINTS:
        input_tap(point)
        time.sleep(1.0)
        if _is_profile_panel_open():
            return True
    capture_state("account_profile_panel_missing")
    capture_page_state("account_profile_panel_missing")
    return False


def _open_crew_warehouse() -> bool:
    go_home()
    time.sleep(0.5)
    for point in CREW_WAREHOUSE_ENTRY_POINTS:
        input_tap(point)
        time.sleep(1.0)
        if _is_crew_warehouse_open():
            return True
        if _tap_plain_confirm_popup():
            if _is_crew_warehouse_open():
                return True
            go_home()
            time.sleep(0.5)
    capture_state("account_profile_crew_warehouse_missing")
    capture_page_state("account_profile_crew_warehouse_missing")
    return False


def _entry_text(entry: dict[str, Any]) -> str:
    return _clean_text(entry.get("text", ""))


def _role_match_keys(
    role: str,
    role_names: tuple[str, ...] | set[str] | None = None,
) -> tuple[str, ...]:
    clean = _clean_text(role)
    keys = [clean]
    role_set = {_clean_text(name) for name in role_names or ()}
    if "·" in clean:
        prefix = clean.split("·", 1)[0]
        if prefix not in role_set:
            keys.append(prefix)
    if "・" in clean:
        prefix = clean.split("・", 1)[0]
        if prefix not in role_set:
            keys.append(prefix)
    normalized = clean.translate(ROLE_OCR_EQUIVALENTS)
    if normalized not in keys:
        keys.append(normalized)
    return tuple(key for key in keys if key)


def _normalized_role_ocr_text(text: str) -> str:
    clean = _clean_text(text)
    return ROLE_OCR_ALIASES.get(clean, clean.translate(ROLE_OCR_EQUIVALENTS))


def _match_role_name(text: str, role_names: tuple[str, ...]) -> str | None:
    clean = _clean_text(text)
    normalized = _normalized_role_ocr_text(text)
    role_set = set(role_names)
    for role in sorted(role_names, key=len, reverse=True):
        if any(key and (key in clean or key in normalized) for key in _role_match_keys(role, role_set)):
            return role
    if len(clean) < 2:
        return None

    best_role: str | None = None
    best_score = 0.0
    for role in role_names:
        for key in _role_match_keys(role, role_set):
            if abs(len(key) - len(normalized)) > 2:
                continue
            score = SequenceMatcher(None, normalized, key).ratio()
            if score > best_score:
                best_role = role
                best_score = score
    if best_role and best_score >= 0.78:
        return best_role
    return None


def _role_text_match_score(
    text: str,
    role: str,
    role_names: tuple[str, ...] | set[str] | None = None,
) -> float:
    clean = _clean_text(text)
    normalized = _normalized_role_ocr_text(text)
    if not clean or not role:
        return 0.0

    role_set = set(role_names or ())
    keys = _role_match_keys(role, role_set)
    for key in keys:
        if clean == key or normalized == key:
            return 3.0 + len(key) * 0.01
    for key in keys:
        if key and (key in clean or key in normalized):
            return 2.0 + len(key) * 0.01
    if len(clean) < 2:
        return 0.0

    best_score = 0.0
    for key in keys:
        if abs(len(key) - len(normalized)) > 2:
            continue
        best_score = max(best_score, SequenceMatcher(None, normalized, key).ratio())
    return best_score


def _entry_resonance_level(text: str) -> int | None:
    clean = _clean_text(text)
    if not clean:
        return None
    if re.search(r"(?:Lv|LV|等级)\d+", clean):
        return None
    match = re.search(r"共振([0-5])", clean)
    if match:
        return int(match.group(1))
    if clean in {str(level) for level in ROLE_RESONANCE_LEVELS}:
        return int(clean)
    if len(clean) <= 3:
        numbers = _numbers(clean)
        if len(numbers) == 1 and numbers[0] in ROLE_RESONANCE_LEVELS:
            return numbers[0]
    return None


def _crew_sort_arrow_down(raw: Any, sort_entry: dict[str, Any]) -> bool | None:
    """Best-effort check for the down arrow left of 获取时间."""
    left, top, _, bottom = _entry_bounds(sort_entry)
    x1 = max(0, int(left) - 42)
    x2 = max(0, int(left) - 4)
    y1 = max(0, int(top) - 12)
    y2 = max(y1 + 1, int(bottom) + 12)
    crop = raw[y1:y2, x1:x2]
    if crop.size == 0:
        return None
    if crop.ndim == 3:
        gray = crop.mean(axis=2)
    else:
        gray = crop
    dark = gray < 190
    ys, xs = np.where(dark)
    if len(ys) < 8:
        return None
    height = max(1, dark.shape[0])
    top_pixels = int((ys < height * 0.45).sum())
    bottom_pixels = int((ys > height * 0.55).sum())
    if abs(top_pixels - bottom_pixels) < max(4, len(ys) * 0.12):
        return None
    # The down chevron has two upper arms and a lower point, so its upper half
    # normally contains more dark pixels than an up chevron.
    arrow_down = top_pixels > bottom_pixels
    logger.debug(
        f"乘员获取时间排序箭头检测: top={top_pixels}, bottom={bottom_pixels}, down={arrow_down}"
    )
    return arrow_down


def _ensure_crew_sort_by_acquired_time() -> bool:
    for attempt in range(3):
        raw = screenshot_image()
        entries = predict(raw)
        sort_entry = next(
            (entry for entry in entries if any(text in _entry_text(entry) for text in CREW_SORT_TEXTS)),
            None,
        )
        if sort_entry is None:
            if attempt == 0:
                input_tap((1015, 118))
                time.sleep(0.6)
                continue
            capture_state("account_profile_crew_sort_missing", raw)
            capture_page_state("account_profile_crew_sort_missing")
            return False

        arrow_down = _crew_sort_arrow_down(raw, sort_entry)
        if arrow_down is True:
            return True
        if arrow_down is None and attempt > 0:
            logger.debug("乘员获取时间排序箭头方向未能可靠识别，按当前排序继续扫描")
            return True

        x, y = _entry_center(sort_entry)
        input_tap((int(x), int(y)))
        time.sleep(0.7)
    return True


def _crew_snapshot() -> tuple[Any, list[dict[str, Any]]]:
    raw = screenshot_image()
    return raw, predict(raw, cropped_pos1=CREW_LIST_CROP1, cropped_pos2=CREW_LIST_CROP2)


def _crew_entries() -> list[dict[str, Any]]:
    _, entries = _crew_snapshot()
    return entries


def _crew_scale(image: Any) -> tuple[float, float]:
    height, width = image.shape[:2]
    return width / 1280.0, height / 720.0


def _clip_rect(
    rect: tuple[float, float, float, float],
    width: int,
    height: int,
) -> tuple[int, int, int, int] | None:
    x1, y1, x2, y2 = rect
    left = max(0, min(width, int(round(x1))))
    top = max(0, min(height, int(round(y1))))
    right = max(0, min(width, int(round(x2))))
    bottom = max(0, min(height, int(round(y2))))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _crop_rect(image: Any, rect: tuple[int, int, int, int]) -> Any:
    left, top, right, bottom = rect
    return image[top:bottom, left:right]


def _crew_card_bottom_rarity(card_crop: Any) -> str | None:
    if card_crop is None or card_crop.size == 0:
        return None
    height, width = card_crop.shape[:2]
    if height < 120 or width < 80:
        return None

    bottom_from, bottom_to = CREW_CARD_RARITY_STRIPE_FROM_BOTTOM
    top = max(0, height - bottom_from)
    bottom = max(top + 1, height - bottom_to)
    stripe = card_crop[top:bottom, max(0, int(width * 0.04)) : min(width, int(width * 0.96))]
    if stripe.size == 0:
        return None

    hsv = cv2.cvtColor(stripe, cv2.COLOR_BGR2HSV)
    hue = hsv[:, :, 0]
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    visible = value > 55
    color_counts = {
        "blue": int(((hue >= 88) & (hue <= 125) & (saturation > 68) & visible).sum()),
        "purple": int(((hue >= 126) & (hue <= 165) & (saturation > 55) & visible).sum()),
        "gold": int(((hue >= 8) & (hue <= 42) & (saturation > 68) & visible).sum()),
    }
    stripe_area = stripe.shape[0] * stripe.shape[1]
    color_threshold = max(90, int(stripe_area * 0.025))
    best_color, best_color_count = max(color_counts.items(), key=lambda item: item[1])
    second_color_count = max(
        (count for rarity, count in color_counts.items() if rarity != best_color),
        default=0,
    )
    if best_color_count >= color_threshold and best_color_count >= second_color_count * 1.18:
        return best_color

    gray_count = int(((saturation < 48) & (value > 70) & (value < 225)).sum())
    if gray_count >= max(120, int(stripe_area * 0.05)):
        return "gray"
    return None


def _crew_card_allows_resonance_5(rarity: str | None) -> bool | None:
    if rarity in {"SR", "SSR", "purple", "gold"}:
        return True
    if rarity in {"N", "R", "gray", "blue"}:
        return False
    return None


def _role_allows_resonance_5(role: str | None, visual_rarity: str | None = None) -> bool | None:
    max_level = _role_catalog_resonance_max(role)
    if max_level is not None:
        return max_level >= 5
    catalog_rarity = _role_catalog_rarity(role)
    if catalog_rarity:
        return _crew_card_allows_resonance_5(catalog_rarity)
    return _crew_card_allows_resonance_5(visual_rarity)


def _crew_card_column_index(name_x: float, image_width: int) -> int:
    scale_x = image_width / 1280.0
    card_width = CREW_CARD_BASE_WIDTH * scale_x
    return min(
        range(len(CREW_CARD_BASE_LEFTS)),
        key=lambda index: abs(
            name_x
            - (
                CREW_CARD_BASE_LEFTS[index] * scale_x
                + card_width * 0.82
            )
        ),
    )


def _crew_group_name_rows(
    items: list[tuple[str, str, float, float, float, dict[str, Any], int]],
    image_height: int,
) -> list[list[tuple[str, str, float, float, float, dict[str, Any], int]]]:
    scale_y = image_height / 720.0
    rows: list[list[tuple[str, str, float, float, float, dict[str, Any], int]]] = []
    row_tolerance = 42 * scale_y
    for item in sorted(items, key=lambda value: (value[4], value[3])):
        y = item[4]
        for row in rows:
            row_y = float(np.median([entry[4] for entry in row]))
            if abs(y - row_y) <= row_tolerance:
                row.append(item)
                break
        else:
            rows.append([item])
    return rows


def _crew_role_card_candidates(
    image: Any,
    entries: list[dict[str, Any]],
    role_names: tuple[str, ...],
    *,
    include_unmatched: bool = False,
) -> list[CrewRoleCardCandidate]:
    if image is None:
        return []
    height, width = image.shape[:2]
    scale_x, scale_y = _crew_scale(image)
    role_set = set(role_names)

    name_items: list[tuple[str, str, float, float, float, dict[str, Any], int]] = []
    for entry in entries:
        text = _entry_text(entry)
        role = _match_role_name(text, role_names)
        if not role and include_unmatched and _looks_like_crew_name_text(text):
            role = text
        if not role:
            continue
        name_x, name_y = _entry_center(entry)
        if name_y < CREW_SAFE_NAME_Y_MIN * scale_y or name_y > CREW_SAFE_NAME_Y_MAX * scale_y:
            logger.debug(f"跳过边缘乘员卡片: role={role}, y={name_y:.1f}")
            continue
        match_score = _role_text_match_score(text, role, role_set) if role in role_set else 1.0
        column_index = _crew_card_column_index(name_x, width)
        name_items.append((role, text, match_score, name_x, name_y, entry, column_index))

    candidates: list[CrewRoleCardCandidate] = []
    seen_keys: set[tuple[str, int, int]] = set()
    for row in _crew_group_name_rows(name_items, height):
        row_y = float(np.median([item[4] for item in row]))
        row_top = row_y - CREW_CARD_NAME_ROW_TO_TOP * scale_y
        for role, text, match_score, name_x, name_y, entry, column_index in row:
            card_left = CREW_CARD_BASE_LEFTS[column_index] * scale_x
            card_right = card_left + CREW_CARD_BASE_WIDTH * scale_x
            card_rect = _clip_rect(
                (
                    card_left,
                    row_top,
                    card_right,
                    row_top + 292 * scale_y,
                ),
                width,
                height,
            )
            full_badge_rect = _clip_rect(
                (
                    card_right + CREW_CARD_FULL_BADGE_FROM_RIGHT[0] * scale_x,
                    row_y + CREW_CARD_FULL_BADGE_FROM_ROW_Y[0] * scale_y,
                    card_right + CREW_CARD_FULL_BADGE_FROM_RIGHT[1] * scale_x,
                    row_y + CREW_CARD_FULL_BADGE_FROM_ROW_Y[1] * scale_y,
                ),
                width,
                height,
            )
            tight_badge_rect = _clip_rect(
                (
                    card_right + CREW_CARD_TIGHT_BADGE_FROM_RIGHT[0] * scale_x,
                    row_y + CREW_CARD_TIGHT_BADGE_FROM_ROW_Y[0] * scale_y,
                    card_right + CREW_CARD_TIGHT_BADGE_FROM_RIGHT[1] * scale_x,
                    row_y + CREW_CARD_TIGHT_BADGE_FROM_ROW_Y[1] * scale_y,
                ),
                width,
                height,
            )
            if card_rect is None or full_badge_rect is None or tight_badge_rect is None:
                continue
            search_badge_rect = _clip_rect(
                (
                    tight_badge_rect[0] - 12 * scale_x,
                    tight_badge_rect[1] - 24 * scale_y,
                    tight_badge_rect[2] + 12 * scale_x,
                    tight_badge_rect[3] + 24 * scale_y,
                ),
                width,
                height,
            )
            if search_badge_rect is None:
                continue
            key = (role, column_index, int(row_y // max(1, 24 * scale_y)))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            card_crop = _crop_rect(image, card_rect)
            full_badge_crop = _crop_rect(image, full_badge_rect)
            tight_badge_crop = _crop_rect(image, tight_badge_rect)
            search_badge_crop = _crop_rect(image, search_badge_rect)
            if (
                card_crop.size == 0
                or card_crop.shape[0] < 160
                or card_crop.shape[1] < 80
                or full_badge_crop.size == 0
                or tight_badge_crop.size == 0
                or search_badge_crop.size == 0
                or tight_badge_crop.shape[0] < 50
                or tight_badge_crop.shape[1] < 30
            ):
                continue
            visual_rarity = _crew_card_bottom_rarity(card_crop)
            catalog_rarity = _role_catalog_rarity(role)
            rarity = catalog_rarity or visual_rarity
            candidates.append(
                CrewRoleCardCandidate(
                    role=role,
                    text=text,
                    match_score=match_score,
                    name_x=name_x,
                    name_y=name_y,
                    row_y=row_y,
                    column_index=column_index,
                    card_rect=card_rect,
                    card_crop=card_crop,
                    visual_rarity=visual_rarity,
                    catalog_rarity=catalog_rarity,
                    rarity=rarity,
                    allows_resonance_5=_role_allows_resonance_5(role, visual_rarity),
                    full_badge_rect=full_badge_rect,
                    tight_badge_rect=tight_badge_rect,
                    search_badge_rect=search_badge_rect,
                    full_badge_crop=full_badge_crop,
                    tight_badge_crop=tight_badge_crop,
                    search_badge_crop=search_badge_crop,
                    entry=entry,
                )
            )
    return candidates


def _ocr_resonance_badge_level(crop: Any) -> int | None:
    if crop is None or crop.size == 0:
        return None
    variants: list[Any] = []
    variants.append(crop)
    variants.append(cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC))

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, bright = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY)
    variants.append(
        cv2.cvtColor(
            cv2.resize(bright, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST),
            cv2.COLOR_GRAY2BGR,
        )
    )

    for image in variants:
        texts = [_clean_text(entry.get("text", "")) for entry in predict(image)]
        for text in texts:
            match = re.search(r"共振([0-5])", text)
            if match:
                return _config_role_level(int(match.group(1)))
            if text in {str(level) for level in ROLE_RESONANCE_LEVELS}:
                return _config_role_level(int(text))
    return None


def _focus_resonance_badge_crop(crop: Any) -> Any:
    """Keep only the upper-right resonance badge area.

    The card top-left skill marks look similar to resonance shapes and were the
    main source of false low-level readings. The badge itself is anchored on the
    card's upper-right edge, so a conservative right-side focus is safer than
    interpreting the whole card corner.
    """
    if crop is None or crop.size == 0:
        return crop
    height, width = crop.shape[:2]
    if width < 24 or height < 24:
        return crop
    left = 0
    if width >= 70:
        left = int(width * 0.18)
    elif width >= 52:
        left = int(width * 0.08)
    return crop[:, left:]


def _badge_bright_mask(crop: Any, size: tuple[int, int] = (90, 94)) -> np.ndarray | None:
    if crop is None or crop.size == 0:
        return None
    crop = _focus_resonance_badge_crop(crop)
    resized = cv2.resize(crop, size, interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    return (
        ((gray > 135) & ((saturation < 210) | (value > 190)))
        | ((gray > 95) & (saturation < 110))
    ).astype(np.uint8)


def _looks_like_resonance_badge_crop(crop: Any) -> bool:
    """Reject crops that contain card decorations instead of the badge itself."""
    mask = _badge_bright_mask(crop)
    if mask is None:
        return False
    h, w = mask.shape

    # The actual badge always has a horizontal RESONANCE label near the middle
    # plus the large digit above/right of it. The card's left-top diamonds are
    # also bright, but they lack this dense label band.
    label_pixels = int(mask[int(h * 0.34) : int(h * 0.62), int(w * 0.12) :].sum())
    digit_pixels = int(
        mask[: int(h * 0.34), int(w * 0.20) :].sum()
        + mask[int(h * 0.58) :, int(w * 0.32) :].sum()
    )
    return (
        label_pixels >= CREW_BADGE_MIN_LABEL_PIXELS
        and digit_pixels >= CREW_BADGE_MIN_DIGIT_PIXELS
    )


def _crop_alpha_bbox(
    image: np.ndarray,
    alpha: np.ndarray,
    *,
    pad: int = 1,
) -> tuple[np.ndarray, np.ndarray] | None:
    ys, xs = np.where(alpha > 8)
    if not len(xs) or not len(ys):
        return None
    height, width = alpha.shape[:2]
    x1 = max(0, int(xs.min()) - pad)
    x2 = min(width, int(xs.max()) + pad + 1)
    y1 = max(0, int(ys.min()) - pad)
    y2 = min(height, int(ys.max()) + pad + 1)
    if x2 <= x1 or y2 <= y1:
        return None
    return image[y1:y2, x1:x2], alpha[y1:y2, x1:x2]


def _decode_awake_icon_template(level: int, encoded: str) -> tuple[np.ndarray, np.ndarray] | None:
    try:
        raw = base64.b64decode(encoded)
    except (TypeError, ValueError):
        return None
    image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None or image.size == 0:
        return None

    if image.ndim == 2:
        gray = image
        alpha = np.full(gray.shape, 255, dtype=np.uint8)
    elif image.shape[2] == 4:
        alpha = image[:, :, 3]
        bgr = image[:, :, :3]
        cropped = _crop_alpha_bbox(bgr, alpha)
        if cropped is None:
            return None
        bgr, alpha = cropped
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    else:
        gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_BGR2GRAY)
        alpha = np.full(gray.shape, 255, dtype=np.uint8)

    mask = (alpha > 18).astype(np.uint8) * 255
    if int(mask.sum()) <= 0:
        return None
    return gray.astype(np.uint8), mask


@lru_cache(maxsize=1)
def _awake_icon_template_variants() -> tuple[CrewAwakeIconTemplate, ...]:
    data = read_json(CREW_AWAKE_ICON_TEMPLATE_PATH, {})
    raw_icons = data.get("icons") if isinstance(data, dict) else None
    if not isinstance(raw_icons, dict):
        return ()

    variants: list[CrewAwakeIconTemplate] = []
    for raw_level, encoded in raw_icons.items():
        try:
            level = int(raw_level)
        except (TypeError, ValueError):
            continue
        if level not in ROLE_RESONANCE_LEVELS or not isinstance(encoded, str):
            continue
        decoded = _decode_awake_icon_template(level, encoded)
        if decoded is None:
            continue
        gray, mask = decoded
        base_height, base_width = gray.shape[:2]
        for scale in CREW_AWAKE_TEMPLATE_SCALES:
            width = int(round(base_width * scale))
            height = int(round(base_height * scale))
            if width < 18 or height < 18:
                continue
            interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            resized_gray = cv2.resize(
                gray,
                (width, height),
                interpolation=interpolation,
            ).astype(np.uint8)
            resized_mask = cv2.resize(
                mask,
                (width, height),
                interpolation=cv2.INTER_NEAREST,
            ).astype(np.uint8)
            if int(resized_mask.sum()) <= 0:
                continue
            variants.append(
                CrewAwakeIconTemplate(
                    level=level,
                    scale=float(scale),
                    gray=resized_gray,
                    mask=resized_mask,
                )
            )
    return tuple(variants)


def _crop_to_gray(crop: Any) -> np.ndarray | None:
    if crop is None or crop.size == 0:
        return None
    if crop.ndim == 2:
        return crop.astype(np.uint8)
    if crop.ndim != 3:
        return None
    if crop.shape[2] == 4:
        return cv2.cvtColor(crop, cv2.COLOR_BGRA2GRAY)
    return cv2.cvtColor(crop[:, :, :3], cv2.COLOR_BGR2GRAY)


def _awake_icon_template_match(
    crop: Any,
    *,
    allowed_levels: set[int] | None = None,
    min_score: float = CREW_AWAKE_TEMPLATE_MATCH_MIN,
    min_margin: float = CREW_AWAKE_TEMPLATE_MATCH_MARGIN,
) -> tuple[int, float, float] | None:
    gray = _crop_to_gray(_focus_resonance_badge_crop(crop))
    if gray is None:
        return None
    templates = _awake_icon_template_variants()
    if not templates:
        return None

    crop_height, crop_width = gray.shape[:2]
    if crop_height < 24 or crop_width < 24:
        return None
    scores_by_level: dict[int, float] = {}
    for template in templates:
        if allowed_levels is not None and template.level not in allowed_levels:
            continue
        height, width = template.gray.shape[:2]
        if height > crop_height or width > crop_width:
            continue
        try:
            result = cv2.matchTemplate(
                gray,
                template.gray,
                cv2.TM_CCORR_NORMED,
                mask=template.mask,
            )
        except cv2.error:
            continue
        if result.size == 0:
            continue
        result = np.nan_to_num(result, nan=-1.0, posinf=-1.0, neginf=-1.0)
        score = float(result.max())
        if score > scores_by_level.get(template.level, -1.0):
            scores_by_level[template.level] = score

    if not scores_by_level:
        return None
    ranked = sorted(
        ((score, level) for level, score in scores_by_level.items()),
        reverse=True,
    )
    best_score, best_level = ranked[0]
    second_score = ranked[1][0] if len(ranked) > 1 else 0.0
    margin = best_score - second_score
    if best_score >= CREW_AWAKE_TEMPLATE_STRONG_MIN and margin >= min_margin * 0.5:
        return best_level, best_score, margin
    if best_score >= min_score and margin >= min_margin:
        return best_level, best_score, margin
    return None


def _badge_digit_mask(crop: Any) -> np.ndarray | None:
    if crop is None or crop.size == 0:
        return None

    crop = _focus_resonance_badge_crop(crop)
    resized = cv2.resize(crop, (112, 112), interpolation=cv2.INTER_AREA)

    # The badge digit may be white, gray, or gold. Keep bright pixels and muted
    # gray pixels, then remove the constant RESONANCE label band.
    mask = _badge_bright_mask(resized, size=(112, 112))
    if mask is None:
        return None
    h, w = mask.shape
    mask[int(h * 0.32) : int(h * 0.62), :] = 0
    mask[: int(h * 0.04), :] = 0

    kernel = np.ones((2, 2), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    kept = np.zeros_like(mask)
    for index in range(1, num):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < 35:
            continue
        x = int(stats[index, cv2.CC_STAT_LEFT])
        y = int(stats[index, cv2.CC_STAT_TOP])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        if width < 4 or height < 4:
            continue
        kept[labels == index] = 1

    ys, xs = np.where(kept)
    if len(xs) < 120:
        return None
    x1, x2 = int(xs.min()), int(xs.max()) + 1
    y1, y2 = int(ys.min()), int(ys.max()) + 1
    if (x2 - x1) < 18 or (y2 - y1) < 18:
        return None

    pad = 6
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)
    normalized = cv2.resize(
        kept[y1:y2, x1:x2].astype(np.float32),
        CREW_BADGE_TEMPLATE_SIZE,
        interpolation=cv2.INTER_AREA,
    )
    return (normalized > 0.18).astype(np.float32)


def _badge_mask_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_sum = float(left.sum())
    right_sum = float(right.sum())
    if left_sum <= 0 or right_sum <= 0:
        return 0.0
    return float((left * right).sum() / ((left_sum * right_sum) ** 0.5))


def _badge_mask_similarity_shifted(
    left: np.ndarray,
    right: np.ndarray,
    *,
    max_dx: int = 3,
    max_dy: int = 12,
) -> float:
    left_sum = float(left.sum())
    right_sum = float(right.sum())
    if left_sum <= 0 or right_sum <= 0:
        return 0.0

    height, width = left.shape
    best = 0.0
    for dy in range(-max_dy, max_dy + 1, 2):
        if dy >= 0:
            left_y1, left_y2 = dy, height
            right_y1, right_y2 = 0, height - dy
        else:
            left_y1, left_y2 = 0, height + dy
            right_y1, right_y2 = -dy, height
        if left_y2 <= left_y1 or right_y2 <= right_y1:
            continue
        for dx in range(-max_dx, max_dx + 1):
            if dx >= 0:
                left_x1, left_x2 = dx, width
                right_x1, right_x2 = 0, width - dx
            else:
                left_x1, left_x2 = 0, width + dx
                right_x1, right_x2 = -dx, width
            if left_x2 <= left_x1 or right_x2 <= right_x1:
                continue
            overlap = (
                left[left_y1:left_y2, left_x1:left_x2]
                * right[right_y1:right_y2, right_x1:right_x2]
            ).sum()
            best = max(best, float(overlap / ((left_sum * right_sum) ** 0.5)))
    return best


def _remember_badge_template(level: int, crop: Any):
    level = _planner_role_level(level)
    if level not in {1, 4, 5}:
        return
    mask = _badge_digit_mask(crop)
    if mask is None:
        return
    templates = _CREW_BADGE_TEMPLATES.setdefault(level, [])
    if any(_badge_mask_similarity(mask, template) > 0.96 for template in templates):
        return
    if len(templates) < 16:
        templates.append(mask)


def _template_badge_level(crop: Any) -> int | None:
    mask = _badge_digit_mask(crop)
    if mask is None or not _CREW_BADGE_TEMPLATES:
        return None

    scores: list[tuple[float, int]] = []
    for level, templates in _CREW_BADGE_TEMPLATES.items():
        if not templates:
            continue
        scores.append((max(_badge_mask_similarity(mask, template) for template in templates), level))
    if not scores:
        return None
    scores.sort(reverse=True)
    best_score, best_level = scores[0]
    second_score = scores[1][0] if len(scores) > 1 else 0.0
    if (
        best_score >= CREW_BADGE_TEMPLATE_MATCH_MIN
        and best_score - second_score >= CREW_BADGE_TEMPLATE_MATCH_MARGIN
    ):
        return best_level
    return None


@lru_cache(maxsize=1)
def _right_badge_digit_templates() -> dict[int, np.ndarray]:
    width, height = CREW_RIGHT_BADGE_TEMPLATE_SIZE
    bit_count = width * height
    templates: dict[int, np.ndarray] = {}
    for level, encoded in _CREW_RIGHT_BADGE_TEMPLATE_DATA.items():
        padded = encoded + ("=" * (-len(encoded) % 4))
        raw = base64.b64decode(padded)
        bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:bit_count]
        templates[level] = bits.reshape((height, width)).astype(np.float32)
    return templates


def _right_badge_digit_mask(crop: Any) -> np.ndarray | None:
    if crop is None or crop.size == 0:
        return None

    # The reliable signal is the large digit on the card's upper-right
    # RESONANCE badge. The left side of this crop may contain portrait pixels,
    # so keep only the badge side and blank out the text band.
    if crop.shape[1] > 60:
        crop = crop[:, int(crop.shape[1] * 0.36) :]
    width, height = CREW_RIGHT_BADGE_TEMPLATE_SIZE
    resized = cv2.resize(crop, (width, height), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    mask = ((gray > 118) & ((hsv[:, :, 1] < 180) | (gray > 185))).astype(np.float32)

    mask[int(height * 0.34) : int(height * 0.56), :] = 0
    mask[int(height * 0.45) :, :7] = 0
    mask[int(height * 0.40) :, int(width * 0.90) :] = 0
    if int(mask.sum()) < 80:
        return None
    return mask


def _right_badge_template_match(crop: Any) -> tuple[int, float, float] | None:
    mask = _right_badge_digit_mask(crop)
    if mask is None:
        return None
    scores = [
        (_badge_mask_similarity(mask, template), level)
        for level, template in _right_badge_digit_templates().items()
    ]
    scores.sort(reverse=True)
    best_score, best_level = scores[0]
    second_score = scores[1][0] if len(scores) > 1 else 0.0
    if best_score >= 0.35 and best_score - second_score >= 0.08:
        return best_level, best_score, best_score - second_score
    return None


def _right_badge_template_level(crop: Any) -> int | None:
    match = _right_badge_template_match(crop)
    if match is not None:
        return match[0]
    return None


@lru_cache(maxsize=1)
def _tight_right_badge_templates() -> dict[int, list[np.ndarray]]:
    width, height = CREW_TIGHT_RIGHT_BADGE_TEMPLATE_SIZE
    bit_count = width * height
    byte_count = (bit_count + 7) // 8
    expected_encoded_len = ((byte_count + 2) // 3) * 4
    external_data = read_json(CREW_TIGHT_BADGE_TEMPLATE_PATH, {})
    raw_external_templates = (
        external_data.get("templates")
        if isinstance(external_data, dict)
        else None
    )
    raw_templates: dict[Any, Any] = {}
    if isinstance(raw_external_templates, dict) and any(raw_external_templates.values()):
        raw_templates = {
            level: tuple(encoded_items or ())
            for level, encoded_items in raw_external_templates.items()
        }
    else:
        raw_templates = dict(_CREW_TIGHT_RIGHT_BADGE_TEMPLATE_DATA)

    templates: dict[int, list[np.ndarray]] = {}
    for level, encoded_items in raw_templates.items():
        try:
            normalized_level = int(level)
        except (TypeError, ValueError):
            continue
        for encoded in encoded_items:
            if not isinstance(encoded, str):
                continue
            if len(encoded) < expected_encoded_len:
                encoded = ("A" * (expected_encoded_len - len(encoded))) + encoded
            padded = encoded + ("=" * (-len(encoded) % 4))
            try:
                raw = base64.b64decode(padded)
            except ValueError:
                continue
            if len(raw) * 8 < bit_count:
                continue
            bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))[:bit_count]
            template = bits.reshape((height, width)).astype(np.float32)
            # The center band is the constant "RESONANCE" label. Keeping it in
            # the template made low resonance badges look deceptively similar to
            # 4/5, so both templates and live masks ignore that band.
            template[int(height * 0.32) : int(height * 0.58), :] = 0
            templates.setdefault(normalized_level, []).append(template)
    return templates


def _tight_right_badge_digit_mask(crop: Any) -> np.ndarray | None:
    if crop is None or crop.size == 0:
        return None
    if crop.shape[1] > 12:
        crop = crop[:, int(crop.shape[1] * 0.18) :]

    width, height = CREW_TIGHT_RIGHT_BADGE_TEMPLATE_SIZE
    resized = cv2.resize(crop, (width, height), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    mask = (
        ((gray > 140) & (saturation < 195))
        | ((gray > 92) & (saturation < 75))
    ).astype(np.float32)
    mask[int(height * 0.32) : int(height * 0.58), :] = 0
    mask[int(height * 0.58) :, : int(width * 0.16)] = 0
    if int(mask.sum()) < 60:
        return None
    return mask


def _tight_right_badge_template_match(crop: Any) -> tuple[int, float, float] | None:
    mask = _tight_right_badge_digit_mask(crop)
    if mask is None:
        return None
    scores: list[tuple[float, int]] = []
    for level, templates in _tight_right_badge_templates().items():
        if not templates:
            continue
        scores.append(
            (
                max(
                    _badge_mask_similarity_shifted(mask, template, max_dx=3, max_dy=12)
                    for template in templates
                ),
                level,
            )
        )
    if not scores:
        return None
    scores.sort(reverse=True)
    best_score, best_level = scores[0]
    second_score = scores[1][0] if len(scores) > 1 else 0.0
    margin = best_score - second_score
    if best_score >= 0.58 and margin >= 0.045:
        return best_level, best_score, margin
    return None


def _badge_shape_level(crop: Any) -> int | None:
    """Classify the small resonance digit badge by geometry, not text OCR.

    The card badge mixes a big digit with a constant "RESONANCE" label. OCR often
    reads only the label, so this looks at the light/neutral components around
    the digit: resonance 4 is usually split into narrow right-side strokes, while
    resonance 5 has a broad connected top/curve shape.
    """
    if crop is None or crop.size == 0:
        return None

    crop = _focus_resonance_badge_crop(crop)
    crop = cv2.resize(crop, (90, 94), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = ((gray > 125) & (hsv[:, :, 1] < 160)).astype(np.uint8)
    if int(mask.sum()) < 160:
        return None

    h, w = mask.shape
    # Reduce the constant "RESONANCE" text band so it does not dominate.
    shape_mask = mask.copy()
    shape_mask[int(h * 0.35) : int(h * 0.58), :] = 0

    num, labels, stats, _ = cv2.connectedComponentsWithStats(shape_mask, 8)
    components: list[tuple[int, int, int, int, int]] = []
    for index in range(1, num):
        area = int(stats[index, cv2.CC_STAT_AREA])
        if area < 25:
            continue
        x = int(stats[index, cv2.CC_STAT_LEFT])
        y = int(stats[index, cv2.CC_STAT_TOP])
        width = int(stats[index, cv2.CC_STAT_WIDTH])
        height = int(stats[index, cv2.CC_STAT_HEIGHT])
        components.append((area, x, y, width, height))

    if not components:
        return None

    largest = max(components, key=lambda item: item[0])
    largest_area, largest_x, _, largest_width, largest_height = largest
    right_strokes = [
        item
        for item in components
        if item[1] > w * 0.50 and item[3] <= w * 0.42 and item[4] >= h * 0.34
    ]
    left_mass = float(shape_mask[int(h * 0.55) :, : int(w * 0.48)].mean())
    right_mass = float(shape_mask[int(h * 0.55) :, int(w * 0.55) :].mean())
    top_mass = float(shape_mask[: int(h * 0.30), int(w * 0.35) :].mean())
    center_mass = float(shape_mask[int(h * 0.14) : int(h * 0.34), int(w * 0.38) : int(w * 0.66)].mean())
    upper_left_mass = float(shape_mask[int(h * 0.10) : int(h * 0.44), int(w * 0.16) : int(w * 0.42)].mean())
    upper_right_mass = float(shape_mask[int(h * 0.10) : int(h * 0.44), int(w * 0.60) : int(w * 0.86)].mean())
    upper_top_mass = float(shape_mask[int(h * 0.06) : int(h * 0.22), int(w * 0.26) : int(w * 0.78)].mean())

    if right_strokes and (largest_x > w * 0.50 or right_mass > max(0.18, left_mass * 1.25)):
        return 4
    if largest_x > w * 0.50 and largest_width <= w * 0.42 and largest_height >= h * 0.35:
        return 4

    # A narrow mostly vertical stroke is most likely resonance 1/2/3; the planner
    # treats those as resonance 1.
    if largest_width < w * 0.30 and largest_height > h * 0.48:
        return 1
    if (
        right_mass > max(0.10, left_mass * 1.45)
        and largest_width < w * 0.38
        and largest_height > h * 0.38
    ):
        return 1
    if (
        largest_width >= w * 0.38
        and largest_height >= h * 0.38
        and center_mass < 0.12
        and upper_top_mass > 0.11
        and upper_left_mass > 0.08
        and upper_right_mass > 0.08
    ):
        return 0

    broad_component = (
        largest_area >= 1400 and largest_width >= w * 0.55 and largest_height >= h * 0.30
    )
    if broad_component and (largest_area >= 2200 or top_mass > 0.35 or left_mass > 0.45):
        return 5
    return None


def _classify_badge_crop_with_source(crop: Any) -> tuple[int, str] | None:
    awake_match = _awake_icon_template_match(crop)
    if awake_match is not None:
        return awake_match[0], "awake-icon-template"

    if not _looks_like_resonance_badge_crop(crop):
        return None

    right_template_level = _right_badge_template_level(crop)
    if right_template_level is not None:
        return right_template_level, "right-template"

    shape_level = _badge_shape_level(crop)
    if shape_level is not None:
        _remember_badge_template(shape_level, crop)
        return shape_level, "shape"

    template_level = _template_badge_level(crop)
    if template_level is not None:
        return template_level, "template"

    ocr_level = _ocr_resonance_badge_level(crop)
    if ocr_level is not None:
        _remember_badge_template(ocr_level, crop)
        return ocr_level, "ocr"
    return None


def _crew_badge_prediction_from_tight_match(
    match: tuple[int, float, float] | None,
    *,
    source: str = "card-tight-template",
) -> CrewBadgePrediction | None:
    if match is None:
        return None
    level, score, margin = match
    min_score = CREW_CARD_MIN_BADGE_SCORE
    min_margin = CREW_CARD_MIN_BADGE_MARGIN
    if "awake-icon" in source:
        min_score = CREW_AWAKE_TEMPLATE_MATCH_MIN
        min_margin = CREW_AWAKE_TEMPLATE_MATCH_MARGIN
    if score < min_score or margin < min_margin:
        return None
    if "awake-icon" in source:
        if score >= 0.88 and margin >= 0.035:
            weight = 10
        elif score >= 0.84 and margin >= 0.018:
            weight = 8
        elif score >= 0.78 and margin >= 0.014:
            weight = 6
        else:
            weight = 4
    elif score >= 0.88 and margin >= 0.14:
        weight = 8
    elif score >= 0.80 and margin >= 0.10:
        weight = 6
    elif score >= 0.70 and margin >= 0.08:
        weight = 3
    elif score >= 0.68 and margin >= 0.12:
        weight = 2
    else:
        weight = 1
    return CrewBadgePrediction(
        level=level,
        confidence=float(score),
        margin=float(margin),
        weight=weight,
        source=source,
    )


def _apply_crew_card_rarity_cap(
    card: CrewRoleCardCandidate,
    prediction: CrewBadgePrediction | None,
) -> CrewBadgePrediction | None:
    if prediction is None:
        return None
    if prediction.level == 5 and card.allows_resonance_5 is False:
        for crop, source_prefix in (
            (card.tight_badge_crop, "card-tight"),
            (card.full_badge_crop, "card-full"),
            (card.search_badge_crop, "card-search"),
        ):
            awake_match = _awake_icon_template_match(
                crop,
                allowed_levels={0, 1, 2, 3, 4},
                min_score=0.70,
                min_margin=0.006,
            )
            fallback = _crew_badge_prediction_from_tight_match(
                awake_match,
                source=f"{source_prefix}-awake-icon-rarity-cap",
            )
            if fallback is not None and fallback.level != 5:
                return fallback
        for crop, source_prefix in (
            (card.full_badge_crop, "card-full"),
            (card.tight_badge_crop, "card-tight"),
        ):
            shape_level = _badge_shape_level(crop)
            if shape_level in {0, 1, 4}:
                return CrewBadgePrediction(
                    level=shape_level,
                    confidence=0.70,
                    margin=0.0,
                    weight=3,
                    source=f"{source_prefix}-shape-before-rarity-cap",
                )
        logger.debug(
            "乘员共振候选被稀有度上限拦截: role={} rarity={} source={} score={:.3f}",
            card.role,
            card.rarity,
            prediction.source,
            prediction.confidence,
        )
        return None
    return prediction


def _nearby_tight_badge_template_match(
    card: CrewRoleCardCandidate,
) -> tuple[int, float, float] | None:
    search = card.search_badge_crop
    target_height, target_width = card.tight_badge_crop.shape[:2]
    if search is None or search.size == 0:
        return None
    search_height, search_width = search.shape[:2]
    if search_height < target_height or search_width < target_width:
        return None

    matches: list[tuple[float, float, int, int, int]] = []
    center_x = max(0, int(round((search_width - target_width) / 2)))
    center_y = max(0, int(round((search_height - target_height) / 2)))
    x_offsets = (0, -6, 6, -12, 12)
    y_offsets = (0, -8, 8, -16, 16, -24, 24)
    visited: set[tuple[int, int]] = set()
    for dy in y_offsets:
        for dx in x_offsets:
            x = min(max(0, center_x + dx), search_width - target_width)
            y = min(max(0, center_y + dy), search_height - target_height)
            if (x, y) in visited:
                continue
            visited.add((x, y))
            crop = search[y : y + target_height, x : x + target_width]
            match = _tight_right_badge_template_match(crop)
            if match is None:
                continue
            level, score, margin = match
            if score < 0.70 or margin < 0.08:
                continue
            matches.append((float(score), float(margin), _config_role_level(level), x, y))
    if not matches:
        return None

    level_scores: dict[int, tuple[float, float, int]] = {}
    for score, margin, level, x, y in matches:
        current = level_scores.get(level)
        if current is None or (score, margin) > (current[0], current[1]):
            level_scores[level] = (score, margin, len([item for item in matches if item[2] == level]))
    ranked = sorted(
        ((score, margin, count, level) for level, (score, margin, count) in level_scores.items()),
        reverse=True,
    )
    best_score, best_margin, _, best_level = ranked[0]
    if len(ranked) > 1:
        second_score, second_margin, _, second_level = ranked[1]
        if second_level != best_level and best_score - second_score < 0.018 and best_margin < 0.12:
            return None
    return best_level, best_score, best_margin


def _classify_low_resonance_badge(crop: Any, *, allow_slow_ocr: bool = False) -> int | None:
    """Return conservative low-resonance readings from the badge shape."""
    shape_level = _badge_shape_level(crop)
    if shape_level == 0:
        return 0
    if shape_level == 1:
        return 1
    if shape_level in {4, 5}:
        return None
    if not allow_slow_ocr:
        return None
    ocr_level = _ocr_resonance_badge_level(crop)
    if ocr_level == 0:
        return 0
    if ocr_level in {1, 2, 3}:
        return 1
    return None


def _classify_crew_card_badge(
    card: CrewRoleCardCandidate,
) -> CrewBadgePrediction | None:
    awake_predictions: list[CrewBadgePrediction] = []
    for crop, source_prefix in (
        (card.tight_badge_crop, "card-tight"),
        (card.full_badge_crop, "card-full"),
        (card.search_badge_crop, "card-search"),
    ):
        prediction = _crew_badge_prediction_from_tight_match(
            _awake_icon_template_match(crop),
            source=f"{source_prefix}-awake-icon",
        )
        prediction = _apply_crew_card_rarity_cap(card, prediction)
        if prediction is not None:
            awake_predictions.append(prediction)
    if awake_predictions:
        awake_predictions.sort(
            key=lambda item: (item.weight, item.confidence, item.margin),
            reverse=True,
        )
        best_prediction = awake_predictions[0]
        if best_prediction.weight >= 6 or len(awake_predictions) == 1:
            if (
                best_prediction.level in {0, 1}
                and best_prediction.weight < 6
                and best_prediction.confidence < 0.82
                and best_prediction.margin < 0.03
            ):
                logger.debug(
                    "乘员共振弱低阶图标匹配跳过: role={} level={} source={} score={:.3f} margin={:.3f}",
                    card.role,
                    best_prediction.level,
                    best_prediction.source,
                    best_prediction.confidence,
                    best_prediction.margin,
                )
            else:
                return best_prediction
        # If two crops agree, keep the lower-confidence source result too.
        if len({prediction.level for prediction in awake_predictions[:2]}) == 1:
            return best_prediction

    for crop, source_prefix in (
        (card.full_badge_crop, "card-full"),
        (card.tight_badge_crop, "card-tight"),
    ):
        low_level = _classify_low_resonance_badge(
            crop,
            allow_slow_ocr=(
                os.environ.get("NCT_CREW_SLOW_BADGE_OCR") == "1"
                and source_prefix == "card-full"
            ),
        )
        if low_level is None:
            continue
        return CrewBadgePrediction(
            level=_config_role_level(low_level),
            confidence=0.72,
            margin=0.0,
            weight=4,
            source=f"{source_prefix}-low-resonance-first",
        )

    prediction = _crew_badge_prediction_from_tight_match(
        _tight_right_badge_template_match(card.tight_badge_crop)
    )
    prediction = _apply_crew_card_rarity_cap(card, prediction)
    if prediction is not None:
        if prediction.weight >= 6:
            _remember_badge_template(prediction.level, card.full_badge_crop)
            return prediction
        if prediction.weight >= 3:
            return prediction

    nearby_prediction = _crew_badge_prediction_from_tight_match(
        _nearby_tight_badge_template_match(card),
        source="card-tight-nearby-template",
    )
    nearby_prediction = _apply_crew_card_rarity_cap(card, nearby_prediction)
    if nearby_prediction is not None:
        if nearby_prediction.weight >= 6:
            _remember_badge_template(nearby_prediction.level, card.full_badge_crop)
        return nearby_prediction

    if prediction is not None:
        return prediction
    return None


def _classify_badge_crop(crop: Any) -> int | None:
    result = _classify_badge_crop_with_source(crop)
    if result is not None:
        return result[0]
    return None


def _classify_badge_crop_by_template_only(crop: Any) -> int | None:
    if not _looks_like_resonance_badge_crop(crop):
        return None
    return _template_badge_level(crop)


def _classify_role_resonance_from_badge(
    image: Any,
    name_entry: dict[str, Any],
    *,
    weighted: bool = False,
) -> int | tuple[int, int] | None:
    name_x, name_y = _entry_center(name_entry)
    _, _, name_right, _ = _entry_bounds(name_entry)
    height, width = image.shape[:2]
    tight_crop_offsets = (
        (-15, 38, -250, -150),
        (-18, 40, -252, -148),
        (-12, 36, -248, -152),
    )
    tight_template_matches: list[tuple[int, float, float]] = []
    for left, right, top, bottom in tight_crop_offsets:
        x1 = max(0, int(name_x + left))
        x2 = min(width, int(name_x + right))
        y1 = max(0, int(name_y + top))
        y2 = min(height, int(name_y + bottom))
        if x2 <= x1 or y2 <= y1:
            continue
        crop = image[y1:y2, x1:x2]
        awake_match = _awake_icon_template_match(crop)
        if awake_match is not None:
            level, score, margin = awake_match
            tight_template_matches.append((_config_role_level(level), score, margin))
            continue
        tight_match = _tight_right_badge_template_match(crop)
        if tight_match is None:
            continue
        level, score, margin = tight_match
        tight_template_matches.append((_config_role_level(level), score, margin))
    if tight_template_matches:
        level_scores: dict[int, float] = {}
        level_counts: Counter[int] = Counter()
        for level, score, margin in tight_template_matches:
            level_scores[level] = level_scores.get(level, 0.0) + score + margin * 0.35
            level_counts[level] += 1
        level = max(
            level_scores,
            key=lambda item: (level_counts[item], level_scores[item]),
        )
        return (level, 8) if weighted else level

    crop_offsets = (
        (-74, 8, -238, -146),
        (-88, 16, -240, -142),
        (-104, 22, -252, -122),
        (-74, 8, -224, -132),
        (-64, 18, -238, -146),
        (-82, 12, -252, -130),
        (-68, 20, -250, -140),
    )

    template_matches: list[tuple[float, float, int]] = []
    fallback_levels: list[int] = []
    for left, right, top, bottom in crop_offsets:
        x1 = max(0, int(name_right + left))
        x2 = min(width, int(name_right + right))
        y1 = max(0, int(name_y + top))
        y2 = min(height, int(name_y + bottom))
        if x2 <= x1 or y2 <= y1:
            continue
        crop = image[y1:y2, x1:x2]
        awake_match = _awake_icon_template_match(crop)
        if awake_match is not None:
            level, score, margin = awake_match
            template_matches.append((margin, score, _config_role_level(level)))
            continue
        if _looks_like_resonance_badge_crop(crop):
            template_match = _right_badge_template_match(crop)
            if template_match is not None:
                level, score, margin = template_match
                template_matches.append((margin, score, _config_role_level(level)))
                continue
            fallback_result = _classify_badge_crop_with_source(crop)
            if fallback_result is not None and fallback_result[1] != "right-template":
                fallback_levels.append(_config_role_level(fallback_result[0]))

    if template_matches:
        template_matches.sort(reverse=True)
        level = template_matches[0][2]
        return (level, 1) if weighted else level
    if not fallback_levels:
        return None
    counts = Counter(fallback_levels)
    best_count = max(counts.values())
    best_levels = [level for level, count in counts.items() if count == best_count]
    if len(best_levels) == 1 and best_count >= (2 if len(fallback_levels) > 1 else 1):
        level = best_levels[0]
        return (level, 1) if weighted else level
    return None


def parse_role_resonance_from_entries(
    entries: list[dict[str, Any]],
    role_names: tuple[str, ...] | None = None,
    image: Any | None = None,
    *,
    weighted: bool = False,
) -> dict[str, int | tuple[int, int]]:
    role_names = role_names or load_role_catalog_names()
    if image is not None:
        result: dict[str, int | tuple[int, int]] = {}
        result_priority: dict[str, tuple[int, float, float]] = {}
        role_name_set = set(role_names)
        for card in _crew_role_card_candidates(
            image,
            entries,
            role_names,
            include_unmatched=_crew_debug_enabled(),
        ):
            prediction = _classify_crew_card_badge(card)
            _record_crew_recognition_debug(card, prediction)
            if card.role not in role_name_set:
                continue
            if prediction is None:
                logger.debug(
                    "乘员共振低置信跳过: role={} text={} column={} row_y={:.1f} rarity={} tight_rect={}",
                    card.role,
                    card.text,
                    card.column_index,
                    card.row_y,
                    card.rarity,
                    card.tight_badge_rect,
                )
                continue
            level = _config_role_level(prediction.level)
            candidate = (level, prediction.weight) if weighted else level
            priority = (prediction.weight, prediction.confidence, card.match_score)
            if priority > result_priority.get(card.role, (-1, -1.0, -1.0)):
                result[card.role] = candidate
                result_priority[card.role] = priority
                logger.debug(
                    "乘员共振卡片识别: role={} level={} source={} score={:.3f} margin={:.3f} weight={} rarity={} rect={}",
                    card.role,
                    level,
                    prediction.source,
                    prediction.confidence,
                    prediction.margin,
                    prediction.weight,
                    card.rarity,
                    card.tight_badge_rect,
                )
        return result

    cleaned_entries: list[tuple[str, float, float, dict[str, Any]]] = []
    for entry in entries:
        text = _entry_text(entry)
        if not text:
            continue
        x, y = _entry_center(entry)
        cleaned_entries.append((text, x, y, entry))

    result: dict[str, int | tuple[int, int]] = {}
    result_priority: dict[str, tuple[int, float]] = {}
    for text, name_x, name_y, name_entry in cleaned_entries:
        role = _match_role_name(text, role_names)
        if not role:
            continue
        if name_y < CREW_SAFE_NAME_Y_MIN or name_y > CREW_SAFE_NAME_Y_MAX:
            logger.debug(f"跳过边缘乘员卡片: role={role}, y={name_y:.1f}")
            continue
        match_score = _role_text_match_score(text, role, role_names)

        candidates: list[tuple[float, int]] = []
        _, name_top, _, _ = _entry_bounds(name_entry)
        for other_text, x, y, _ in cleaned_entries:
            level = _entry_resonance_level(other_text)
            if level is None:
                continue
            if y < name_y - 120 or y > name_y + 45:
                continue
            if x < name_x - 20:
                continue
            score = abs(y - (name_top - 30)) + max(0, name_x - x) * 0.2
            candidates.append((score, level))

        if not candidates:
            # Some OCR engines merge the resonance icon with nearby text.
            inline_level = _entry_resonance_level(text)
            if inline_level is not None:
                candidates.append((999.0, inline_level))

        if candidates:
            level = _config_role_level(min(candidates, key=lambda item: item[0])[1])
            candidate = (level, 1) if weighted else level
            priority = (candidate[1] if isinstance(candidate, tuple) else 1, match_score)
            if priority > result_priority.get(role, (-1, -1.0)):
                result[role] = candidate
                result_priority[role] = priority
            continue

    return result


def _fake_crew_name_entry(x: float, y: float, width: float = 28.0, height: float = 22.0) -> dict[str, Any]:
    half_w = width / 2
    half_h = height / 2
    return {
        "text": "",
        "position": [
            [x - half_w, y - half_h],
            [x + half_w, y - half_h],
            [x + half_w, y + half_h],
            [x - half_w, y + half_h],
        ],
    }


def _crew_role_name_entries(
    entries: list[dict[str, Any]],
    role_names: tuple[str, ...],
) -> list[tuple[str, float, float, dict[str, Any]]]:
    result: list[tuple[str, float, float, dict[str, Any]]] = []
    seen: set[tuple[str, int, int]] = set()
    for entry in entries:
        role = _match_role_name(_entry_text(entry), role_names)
        x, y = _entry_center(entry)
        if not role or y < CREW_SAFE_NAME_Y_MIN or y > CREW_SAFE_NAME_Y_MAX:
            continue
        key = (role, int(x // 8), int(y // 8))
        if key in seen:
            continue
        seen.add(key)
        result.append((role, x, y, entry))
    return result


def _crew_infer_unlabeled_card_levels(
    image: Any,
    entries: list[dict[str, Any]],
    role_names: tuple[str, ...],
) -> list[tuple[float, int, tuple[str, ...]]]:
    # With card-level badge recognition, guessing a missing role from an
    # unlabeled slot is more dangerous than useful: it can turn one OCR miss
    # into a wrong account configuration. Keep unknown visible cards unresolved
    # and let the full scan decide missing roles.
    return []


def _crew_visible_signature(entries: list[dict[str, Any]], role_names: tuple[str, ...]) -> tuple[str, ...]:
    roles: list[str] = []
    for entry in entries:
        role = _match_role_name(_entry_text(entry), role_names)
        _, y = _entry_center(entry)
        if not role or y < CREW_SAFE_NAME_Y_MIN or y > CREW_SAFE_NAME_Y_MAX:
            continue
        item = f"{role}@{int(y // 24)}"
        if item not in roles:
            roles.append(item)
    return tuple(roles)


def _crew_visible_roles(entries: list[dict[str, Any]], role_names: tuple[str, ...]) -> set[str]:
    roles: set[str] = set()
    for entry in entries:
        role = _match_role_name(_entry_text(entry), role_names)
        _, y = _entry_center(entry)
        if role and CREW_SAFE_NAME_Y_MIN <= y <= CREW_SAFE_NAME_Y_MAX:
            roles.add(role)
    return roles


def _looks_like_crew_name_text(text: str) -> bool:
    if not text:
        return False
    if any(keyword in text for keyword in CREW_NAME_EXCLUDE_KEYWORDS):
        return False
    if any(char.isdigit() for char in text):
        return False
    if not re.search(r"[\u4e00-\u9fff]", text):
        return False
    return len(text) <= 8


def _crew_page_name_signature(entries: list[dict[str, Any]]) -> tuple[str, ...]:
    role_names = load_role_catalog_names()
    items: list[str] = []
    for entry in entries:
        text = _entry_text(entry)
        if not _looks_like_crew_name_text(text):
            continue
        x, y = _entry_center(entry)
        if y < CREW_SAFE_NAME_Y_MIN or y > CREW_SAFE_NAME_Y_MAX:
            continue
        role = _match_role_name(text, role_names) or text
        item = f"{role}@{int(x // 32)}:{int(y // 24)}"
        if item not in items:
            items.append(item)
    return tuple(items)


def _crew_page_name_only_signature(entries: list[dict[str, Any]]) -> tuple[str, ...]:
    role_names = load_role_catalog_names()
    names: list[str] = []
    for entry in entries:
        text = _entry_text(entry)
        if not _looks_like_crew_name_text(text):
            continue
        _, y = _entry_center(entry)
        if y < CREW_SAFE_NAME_Y_MIN or y > CREW_SAFE_NAME_Y_MAX:
            continue
        role = _match_role_name(text, role_names) or text
        if role not in names:
            names.append(role)
    return tuple(sorted(names))


def _crew_unmatched_name_texts(entries: list[dict[str, Any]]) -> list[str]:
    role_names = load_role_catalog_names()
    result: list[str] = []
    for entry in entries:
        text = _entry_text(entry)
        if not _looks_like_crew_name_text(text):
            continue
        _, y = _entry_center(entry)
        if y < CREW_SAFE_NAME_Y_MIN or y > CREW_SAFE_NAME_Y_MAX:
            continue
        if _match_role_name(text, role_names):
            continue
        if text not in result:
            result.append(text)
    return result


def _crew_visible_name_candidates(entries: list[dict[str, Any]]) -> set[str]:
    role_names = load_role_catalog_names()
    names: set[str] = set()
    for entry in entries:
        text = _entry_text(entry)
        if not text:
            continue
        _, y = _entry_center(entry)
        if y < CREW_SAFE_NAME_Y_MIN or y > CREW_SAFE_NAME_Y_MAX:
            continue
        role = _match_role_name(text, role_names)
        if role:
            names.add(role)
            continue
        if not _looks_like_crew_name_text(text):
            continue
        names.add(text)
    return names


def _crew_debug_enabled() -> bool:
    return os.environ.get("NCT_CREW_DEBUG") == "1"


def _reset_crew_recognition_debug_records():
    global _CREW_RECOGNITION_DEBUG_RUN_ID
    _CREW_RECOGNITION_DEBUG_RECORDS.clear()
    _CREW_RECOGNITION_DEBUG_RUN_ID = time.strftime("%Y%m%d_%H%M%S")


def _record_crew_recognition_debug(
    card: CrewRoleCardCandidate,
    prediction: CrewBadgePrediction | None,
):
    if not _crew_debug_enabled():
        return
    confidence = float(prediction.confidence) if prediction is not None else 0.0
    weight = int(prediction.weight) if prediction is not None else 0
    priority = (weight, confidence, float(card.match_score))
    existing = _CREW_RECOGNITION_DEBUG_RECORDS.get(card.role)
    if existing is not None and priority <= tuple(existing.get("priority", (0, 0.0, 0.0))):
        return
    _CREW_RECOGNITION_DEBUG_RECORDS[card.role] = {
        "role": card.role,
        "text": card.text,
        "level": prediction.level if prediction is not None else None,
        "planner_level": _planner_role_level(prediction.level) if prediction is not None else None,
        "source": prediction.source if prediction is not None else "unresolved",
        "confidence": confidence,
        "margin": float(prediction.margin) if prediction is not None else 0.0,
        "weight": weight,
        "match_score": float(card.match_score),
        "rarity": card.rarity,
        "catalog_rarity": card.catalog_rarity,
        "visual_rarity": card.visual_rarity,
        "allows_resonance_5": card.allows_resonance_5,
        "priority": priority,
        "full_badge_crop": card.full_badge_crop.copy(),
        "tight_badge_crop": card.tight_badge_crop.copy(),
        "focused_badge_crop": _focus_resonance_badge_crop(card.full_badge_crop).copy(),
    }


def _save_crew_recognition_debug_sheet(role_names: tuple[str, ...]):
    if not _crew_debug_enabled() or not _CREW_RECOGNITION_DEBUG_RECORDS:
        return
    CREW_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    records = [
        _CREW_RECOGNITION_DEBUG_RECORDS[role]
        for role in role_names
        if role in _CREW_RECOGNITION_DEBUG_RECORDS
    ]
    records.extend(
        record
        for role, record in sorted(_CREW_RECOGNITION_DEBUG_RECORDS.items())
        if role not in set(role_names)
    )
    if not records:
        return

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("Pillow 不可用，跳过乘员共振识别总览图生成")
        return

    font_path = "C:/Windows/Fonts/msyh.ttc"
    try:
        font = ImageFont.truetype(font_path, 17)
        small_font = ImageFont.truetype(font_path, 13)
    except OSError:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    columns = 4
    cell_w = 340
    cell_h = 132
    badge_w = 92
    badge_h = 120
    sheet = Image.new(
        "RGB",
        (columns * cell_w, ((len(records) + columns - 1) // columns) * cell_h),
        (242, 242, 242),
    )
    draw = ImageDraw.Draw(sheet)
    serializable_records: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        col = index % columns
        row = index // columns
        x = col * cell_w
        y = row * cell_h
        draw.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), outline=(210, 210, 210))

        crop = record.get("tight_badge_crop")
        if not isinstance(crop, np.ndarray) or not crop.size:
            crop = record.get("focused_badge_crop")
        if not isinstance(crop, np.ndarray) or not crop.size:
            crop = record.get("full_badge_crop")
        if isinstance(crop, np.ndarray) and crop.size:
            crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            crop_image = Image.fromarray(crop_rgb)
            crop_image.thumbnail((badge_w, badge_h), Image.Resampling.LANCZOS)
            sheet.paste(crop_image, (x + 8, y + 6))

        level = record.get("level")
        planner_level = record.get("planner_level")
        if level is None:
            level_text = "未识别"
        elif planner_level is not None and int(planner_level) != int(level):
            level_text = f"共振{level} -> 计算{planner_level}"
        else:
            level_text = f"共振{level}"
        role = str(record.get("role") or "")
        rarity = record.get("catalog_rarity") or record.get("visual_rarity") or "?"
        source = str(record.get("source") or "")
        confidence = float(record.get("confidence") or 0.0)
        weight = int(record.get("weight") or 0)
        text_x = x + badge_w + 18
        draw.text((text_x, y + 10), f"{index + 1}. {role}", fill=(30, 30, 30), font=font)
        draw.text((text_x, y + 38), f"{level_text}  {rarity}", fill=(0, 104, 150), font=font)
        draw.text((text_x, y + 66), f"{source}", fill=(70, 70, 70), font=small_font)
        draw.text((text_x, y + 90), f"score={confidence:.3f} weight={weight}", fill=(70, 70, 70), font=small_font)

        serializable_records.append(
            {
                key: value
                for key, value in record.items()
                if key not in {"full_badge_crop", "tight_badge_crop", "focused_badge_crop", "priority"}
            }
        )

    sheet_path = CREW_DEBUG_DIR / "crew_recognition_sheet.png"
    records_path = CREW_DEBUG_DIR / "crew_recognition_records.json"
    sheet.save(sheet_path)
    run_id = _CREW_RECOGNITION_DEBUG_RUN_ID or time.strftime("%Y%m%d_%H%M%S")
    timestamped_sheet_path = CREW_DEBUG_DIR / f"crew_recognition_sheet_{run_id}.png"
    if timestamped_sheet_path != sheet_path:
        sheet.save(timestamped_sheet_path)
    records_path.write_text(
        json.dumps(serializable_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    timestamped_records_path = CREW_DEBUG_DIR / f"crew_recognition_records_{run_id}.json"
    if timestamped_records_path != records_path:
        timestamped_records_path.write_text(
            json.dumps(serializable_records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    logger.info("乘员共振识别总览已保存: {}", sheet_path)


def _save_crew_unresolved_debug(
    image: Any,
    entries: list[dict[str, Any]],
    role_names: tuple[str, ...],
    unresolved_roles: set[str],
    page_index: int,
):
    if not unresolved_roles or image is None or not _crew_debug_enabled():
        return
    CREW_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    height, width = image.shape[:2]
    stem = f"page_{page_index:02d}"
    cv2.imwrite(str(CREW_DEBUG_DIR / f"{stem}.png"), image)
    records: list[dict[str, Any]] = []
    card_candidates = {
        card.role: card
        for card in _crew_role_card_candidates(image, entries, role_names)
        if card.role in unresolved_roles
    }
    for entry in entries:
        text = _entry_text(entry)
        role = _match_role_name(text, role_names)
        if role not in unresolved_roles:
            continue
        name_x, name_y = _entry_center(entry)
        left, top, right, bottom = _entry_bounds(entry)
        card_x1 = max(0, int(name_x - 190))
        card_x2 = min(width, int(name_x + 190))
        card_y1 = max(0, int(name_y - 330))
        card_y2 = min(height, int(name_y + 70))
        crop = image[card_y1:card_y2, card_x1:card_x2]
        safe_role = re.sub(r'[\\/:*?"<>|]+', "_", role).strip("_") or "role"
        crop_name = f"{stem}_{safe_role}_{int(name_x)}_{int(name_y)}.png"
        if crop.size:
            cv2.imwrite(str(CREW_DEBUG_DIR / crop_name), crop)
        card = card_candidates.get(role)
        full_badge_name = ""
        tight_badge_name = ""
        if card is not None:
            full_badge_name = f"{stem}_{safe_role}_full_badge.png"
            tight_badge_name = f"{stem}_{safe_role}_tight_badge.png"
            cv2.imwrite(str(CREW_DEBUG_DIR / full_badge_name), card.full_badge_crop)
            cv2.imwrite(str(CREW_DEBUG_DIR / tight_badge_name), card.tight_badge_crop)
        records.append(
            {
                "role": role,
                "text": text,
                "center": [name_x, name_y],
                "bounds": [left, top, right, bottom],
                "crop": crop_name,
                "full_badge_crop": full_badge_name,
                "tight_badge_crop": tight_badge_name,
                "rarity": card.rarity if card is not None else None,
                "catalog_rarity": card.catalog_rarity if card is not None else None,
                "visual_rarity": card.visual_rarity if card is not None else None,
                "allows_resonance_5": card.allows_resonance_5 if card is not None else None,
                "full_badge_rect": list(card.full_badge_rect) if card is not None else None,
                "tight_badge_rect": list(card.tight_badge_rect) if card is not None else None,
            }
        )
    if records:
        (CREW_DEBUG_DIR / f"{stem}.json").write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _normalize_resonance_vote(vote: int | tuple[int, int]) -> tuple[int, int]:
    if isinstance(vote, tuple):
        return _config_role_level(vote[0]), max(1, int(vote[1]))
    return _config_role_level(vote), 1


def _resolve_resonance_votes(votes: list[int | tuple[int, int]]) -> int | None:
    if not votes:
        return None
    normalized_votes = [_normalize_resonance_vote(vote) for vote in votes]
    strong_votes = [(level, weight) for level, weight in normalized_votes if weight >= 8]
    if strong_votes:
        strong_counts: Counter[int] = Counter()
        for level, weight in strong_votes:
            strong_counts[level] += weight
        best_count = max(strong_counts.values())
        best_levels = [
            level for level, count in strong_counts.items() if count == best_count
        ]
        if len(best_levels) == 1:
            return best_levels[0]
        for level, _ in reversed(strong_votes):
            if level in best_levels:
                return level

    counts: Counter[int] = Counter()
    for level, weight in normalized_votes:
        counts[level] += weight
    best_count = max(counts.values())
    if best_count < 2:
        return None
    best_levels = [level for level, count in counts.items() if count == best_count]
    if len(best_levels) == 1:
        return best_levels[0]
    return normalized_votes[-1][0]


def read_role_resonance(
    target_roles: list[str] | tuple[str, ...] | None = None,
    *,
    incremental: bool = False,
    known_roles: list[str] | tuple[str, ...] | None = None,
    fill_missing_as_unowned: bool = True,
    _retry_missing: bool = True,
) -> dict[str, int]:
    if _crew_debug_enabled() and _retry_missing:
        _reset_crew_recognition_debug_records()
    all_role_names = load_role_catalog_names()
    if not all_role_names:
        return {}
    if target_roles:
        all_role_set = set(all_role_names)
        wanted = {
            str(role).strip()
            for role in target_roles
            if str(role).strip() in all_role_set
        }
        role_names = tuple(role for role in all_role_names if role in wanted)
    else:
        role_names = all_role_names
    if not role_names:
        return {}

    known_role_set = {
        str(role).strip()
        for role in (known_roles or [])
        if str(role).strip() in set(all_role_names)
    }
    first_page_only = bool(
        incremental
        and target_roles
        and len(role_names) < len(all_role_names)
    )
    detail = "正在打开乘员仓库"
    if first_page_only:
        detail = f"正在补读新增乘员：{'、'.join(role_names)}"
    emit_run_status("正在读取乘员共振", detail)
    if not _open_crew_warehouse():
        go_home()
        return {}
    if not _ensure_crew_sort_by_acquired_time():
        go_home()
        return {}

    resonance: dict[str, int] = {}
    resonance_votes: dict[str, list[int | tuple[int, int]]] = {}
    unlabeled_card_level_votes: list[int] = []
    seen_names: set[str] = set()
    seen_target_names: set[str] = set()
    seen_signatures: dict[tuple[str, ...], int] = {}
    last_page_signature: tuple[str, ...] = ()
    last_page_name_only_signature: tuple[str, ...] = ()
    same_page_signature_count = 0
    same_page_name_only_count = 0
    last_entries: list[dict[str, Any]] = []
    for attempt in range(CREW_SCROLL_ATTEMPTS):
        time.sleep(CREW_PAGE_SETTLE_SECONDS)
        raw, entries = _crew_snapshot()
        last_entries = entries
        page_roles = parse_role_resonance_from_entries(entries, role_names, image=raw, weighted=True)
        signature = _crew_visible_signature(entries, role_names)
        page_signature = _crew_page_name_signature(entries)
        page_name_only_signature = _crew_page_name_only_signature(entries)
        page_target_roles = _crew_visible_roles(entries, role_names)
        page_configurable_roles = _crew_visible_roles(entries, all_role_names)
        if not page_roles and not signature:
            time.sleep(0.7)
            raw, entries = _crew_snapshot()
            last_entries = entries
            page_roles = parse_role_resonance_from_entries(entries, role_names, image=raw, weighted=True)
            signature = _crew_visible_signature(entries, role_names)
            page_signature = _crew_page_name_signature(entries)
            page_name_only_signature = _crew_page_name_only_signature(entries)
            page_target_roles = _crew_visible_roles(entries, role_names)
            page_configurable_roles = _crew_visible_roles(entries, all_role_names)
        unresolved_page_roles = page_target_roles - set(page_roles)
        if unresolved_page_roles:
            time.sleep(CREW_RETRY_SETTLE_SECONDS)
            retry_raw, retry_entries = _crew_snapshot()
            retry_roles = parse_role_resonance_from_entries(
                retry_entries,
                role_names,
                image=retry_raw,
                weighted=True,
            )
            retry_target_roles = _crew_visible_roles(retry_entries, role_names)
            for role, level in retry_roles.items():
                if role in unresolved_page_roles and role not in page_roles:
                    page_roles[role] = level
            page_target_roles.update(retry_target_roles)
            page_configurable_roles.update(_crew_visible_roles(retry_entries, all_role_names))
            retry_signature = _crew_page_name_signature(retry_entries)
            if len(retry_signature) >= len(page_signature):
                page_signature = retry_signature
                page_name_only_signature = _crew_page_name_only_signature(retry_entries)
        for role, level in page_roles.items():
            if isinstance(level, tuple):
                vote_level = _config_role_level(level[0])
                vote_weight = max(1, int(level[1]))
            else:
                vote_level = _config_role_level(level)
                vote_weight = 1
            resonance_votes.setdefault(role, []).append((vote_level, vote_weight))
            resolved = _resolve_resonance_votes(resonance_votes[role])
            if resolved is None:
                resonance.pop(role, None)
            else:
                resonance[role] = resolved
        page_names = _crew_visible_name_candidates(entries)
        unlabeled_card_levels = _crew_infer_unlabeled_card_levels(raw, entries, role_names)
        if unlabeled_card_levels:
            unlabeled_card_level_votes.extend(level for _, level, _ in unlabeled_card_levels)
            logger.debug("乘员页面未命名卡片候选: {}", unlabeled_card_levels)
        seen_names.update(page_names)
        seen_target_names.update(page_target_roles)
        if signature:
            seen_signatures[signature] = seen_signatures.get(signature, 0) + 1
        if page_signature and page_signature == last_page_signature:
            same_page_signature_count += 1
        else:
            last_page_signature = page_signature
            same_page_signature_count = 1 if page_signature else 0
        if page_name_only_signature and page_name_only_signature == last_page_name_only_signature:
            same_page_name_only_count += 1
        else:
            last_page_name_only_signature = page_name_only_signature
            same_page_name_only_count = 1 if page_name_only_signature else 0
        unmatched_names = _crew_unmatched_name_texts(entries)
        logger.debug(
            f"乘员共振扫描第 {attempt + 1} 页: names={sorted(page_names)}, visible={signature}, "
            f"same_page={same_page_signature_count}, same_names={same_page_name_only_count}, "
            f"unmatched={unmatched_names}, parsed={page_roles}"
        )
        _save_crew_unresolved_debug(
            raw,
            entries,
            role_names,
            page_target_roles - set(page_roles),
            attempt + 1,
        )

        emit_run_status(
            "正在读取乘员共振",
            f"已识别共振 {len(resonance)}/{len(role_names)}",
        )
        if len(resonance) >= len(role_names):
            break
        if first_page_only:
            unresolved_first_page_roles = page_configurable_roles - known_role_set - set(page_roles)
            if not unresolved_first_page_roles:
                for role in role_names:
                    if role not in seen_target_names:
                        resonance[role] = -1
                break
            first_page_only = False
            logger.info(
                "新增乘员增量判断未满足第一页全量已有数据条件，继续完整扫描: {}",
                sorted(unresolved_first_page_roles),
            )
        if signature and seen_signatures[signature] >= CREW_SCROLL_STALE_LIMIT:
            break
        if same_page_signature_count >= CREW_SCROLL_STALE_LIMIT and len(page_signature) >= 2:
            logger.info(
                "乘员仓库页面连续 {} 次相同，停止继续下滑: {}",
                same_page_signature_count,
                page_signature,
            )
            break
        if same_page_name_only_count >= CREW_SCROLL_STALE_LIMIT and len(page_name_only_signature) >= 2:
            logger.info(
                "乘员仓库姓名集合连续 {} 次相同，停止继续下滑: {}",
                same_page_name_only_count,
                page_name_only_signature,
            )
            break
        input_swipe(CREW_SCROLL_START, CREW_SCROLL_END, swipe_time=CREW_SCROLL_TIME_MS)
        time.sleep(CREW_AFTER_SCROLL_SECONDS)

    missing_roles = [role for role in role_names if role not in resonance]
    if len(missing_roles) == 1 and unlabeled_card_level_votes:
        inferred_level = _resolve_resonance_votes(unlabeled_card_level_votes)
        if inferred_level is not None:
            role = missing_roles[0]
            resonance[role] = inferred_level
            missing_roles = []
            logger.info("乘员共振通过未命名卡片兜底识别: {}={}", role, inferred_level)
    ambiguous_roles = [
        role
        for role in role_names
        if role in resonance
        and len(
            {
                _normalize_resonance_vote(vote)[0]
                for vote in resonance_votes.get(role, [])
            }
        )
        > 1
    ]
    retry_roles = list(dict.fromkeys(missing_roles + ambiguous_roles))
    if retry_roles and _retry_missing:
        logger.info("乘员共振缺失或冲突，执行目标复扫: {}", retry_roles)
        go_home()
        retry_result = read_role_resonance(
            target_roles=tuple(retry_roles),
            incremental=False,
            fill_missing_as_unowned=False,
            _retry_missing=False,
        )
        for role in retry_roles:
            retry_level = retry_result.get(role)
            if retry_level is not None:
                resonance[role] = _config_role_level(retry_level)
        missing_roles = [role for role in role_names if role not in resonance]
    unseen_missing_roles = [role for role in missing_roles if role not in seen_target_names]
    seen_unresolved_roles = [role for role in missing_roles if role in seen_target_names]
    if unseen_missing_roles and fill_missing_as_unowned and seen_names:
        for role in unseen_missing_roles:
            resonance[role] = -1
        logger.warning("乘员共振未扫描到，已按未拥有写入: {}", unseen_missing_roles)
        missing_roles = [role for role in role_names if role not in resonance]
    if seen_unresolved_roles:
        logger.warning("乘员已扫描到但共振置信不足，保持缺失不写入: {}", seen_unresolved_roles)
    elif missing_roles:
        logger.warning("乘员共振仍未识别: {}", missing_roles)
    if not resonance:
        capture_state(
            "account_profile_role_resonance_missing",
            extra={"texts": [entry.get("text", "") for entry in last_entries[:80]]},
        )
        capture_page_state(
            "account_profile_role_resonance_missing",
            extra={"texts": [entry.get("text", "") for entry in last_entries[:80]]},
        )
        _save_crew_recognition_debug_sheet(role_names)
        go_home()
        return {}

    _save_crew_recognition_debug_sheet(role_names)
    go_home()
    logger.info(
        "乘员仓库扫描完成: scanned_names={} role_resonance={}/{}",
        len(seen_names),
        len(resonance),
        len(role_names),
    )
    emit_run_status(
        "乘员共振读取完成",
        f"已识别共振 {len(resonance)}/{len(role_names)}",
    )
    return resonance


def _tap_prestige_eye() -> bool:
    raw = screenshot_image()
    entries = predict(raw)
    prestige_entry: dict[str, Any] | None = None
    for entry in entries:
        if "声望总和" not in _clean_text(entry.get("text", "")):
            continue
        prestige_entry = entry
        break

    if prestige_entry is not None:
        label_x, label_y = _entry_center(prestige_entry)
        same_row_entries: list[tuple[float, float, dict[str, Any]]] = []
        for entry in entries:
            text = _clean_text(entry.get("text", ""))
            if not any(ch.isdigit() for ch in text):
                continue
            x, y = _entry_center(entry)
            if x <= label_x or abs(y - label_y) > 28:
                continue
            same_row_entries.append((x, y, entry))
        if same_row_entries:
            _, y, value_entry = min(same_row_entries, key=lambda item: item[0])
            _, _, max_x, _ = _entry_bounds(value_entry)
            input_tap((int(max_x - 14), int(y)))
            return True

        input_tap((int(label_x + 175), int(label_y)))
        return True

    input_tap(PROFILE_PRESTIGE_EYE_POINT)
    return True


def _prestige_dialog_entries() -> list[dict[str, Any]]:
    raw = screenshot_image()
    return predict(
        raw,
        cropped_pos1=PROFILE_PRESTIGE_DIALOG_CROP1,
        cropped_pos2=PROFILE_PRESTIGE_DIALOG_CROP2,
    )


def _is_prestige_dialog_open() -> bool:
    entries = _prestige_dialog_entries()
    texts = [_clean_text(entry.get("text", "")) for entry in entries]
    return any("所有城市声望" in text for text in texts) or bool(
        parse_city_prestige_values_from_entries(entries)
    )


def open_profile_prestige_dialog() -> bool:
    emit_run_status("正在读取账号配置", "正在打开个人资料")
    if not _open_profile_panel():
        return False

    if not _tap_ocr_text(("查看更多信息",), fallback=PROFILE_MORE_INFO_POINT):
        capture_state("account_profile_more_info_missing")
        capture_page_state("account_profile_more_info_missing")
        return False

    time.sleep(0.8)
    for _ in range(2):
        emit_run_status("正在读取城市声望", "正在打开所有城市声望列表")
        _tap_prestige_eye()
        time.sleep(0.8)
        if _is_prestige_dialog_open():
            return True

    capture_state("account_profile_prestige_dialog_missing")
    capture_page_state("account_profile_prestige_dialog_missing")
    return False


def close_profile_prestige_dialog() -> None:
    input_tap(PROFILE_PRESTIGE_DIALOG_CONFIRM_POINT)
    time.sleep(0.4)
    input_tap(PROFILE_PANEL_CLOSE_POINT)
    time.sleep(0.5)


def reset_profile_prestige_scroll() -> None:
    return None


def read_profile_city_prestige() -> tuple[dict[str, int], dict[str, int]]:
    """Open profile details and parse every city prestige from the prestige dialog."""
    emit_run_status("正在读取城市声望", "正在进入个人资料声望列表")
    if not open_profile_prestige_dialog():
        go_home()
        return {}, {}

    reset_profile_prestige_scroll()
    values: dict[str, int] = {}
    stale_scrolls = 0
    last_count = 0
    entries: list[dict[str, Any]] = []
    for attempt in range(PROFILE_PRESTIGE_SCROLL_ATTEMPTS + 1):
        entries = _prestige_dialog_entries()
        page_values = parse_city_prestige_values_from_entries(entries)
        if not page_values:
            page_values = parse_city_prestige_values(
                [entry.get("text", "") for entry in entries]
            )
        values.update(page_values)
        if len(values) == last_count:
            stale_scrolls += 1
        else:
            stale_scrolls = 0
            last_count = len(values)
        if stale_scrolls >= 2:
            break
        if attempt < PROFILE_PRESTIGE_SCROLL_ATTEMPTS:
            emit_run_status(
                "正在读取城市声望",
                f"已识别 {len(values)} 个城市，继续滑动读取",
            )
            input_swipe(
                PROFILE_PRESTIGE_SCROLL_START,
                PROFILE_PRESTIGE_SCROLL_END,
                swipe_time=700,
            )
            time.sleep(0.8)

    if not values:
        raw = screenshot_image()
        capture_state(
            "account_profile_city_prestige_missing",
            raw,
            extra={"texts": [entry.get("text", "") for entry in entries[:80]]},
        )
        capture_page_state(
            "account_profile_city_prestige_missing",
            extra={"texts": [entry.get("text", "") for entry in entries[:80]]},
        )

    close_profile_prestige_dialog()
    emit_run_status("城市声望读取完成", f"已识别 {len(values)} 个城市声望")
    return values, prestige_values_to_levels(values)


def read_current_city_prestige(city_name: str) -> int | None:
    if not go_city():
        capture_state("account_profile_go_city_failed", extra={"city": city_name})
        capture_page_state("account_profile_go_city_failed", extra={"city": city_name})
        return None
    texts = ocr_texts()
    level = parse_prestige_level(texts)
    if level is None:
        capture_state(
            "account_profile_prestige_missing",
            extra={"city": city_name, "texts": texts[:40]},
        )
        capture_page_state(
            "account_profile_prestige_missing",
            extra={"city": city_name, "texts": texts[:40]},
        )
    return level


def read_cargo_capacity() -> int | None:
    emit_run_status("正在读取货舱", "正在进入交易所读取货舱上限")
    if not go_business("buy"):
        capture_state("account_profile_buy_page_failed")
        capture_page_state("account_profile_buy_page_failed")
        return None
    texts = ocr_texts(cropped_pos1=CARGO_CROP_POS1, cropped_pos2=CARGO_CROP_POS2)
    capacity = parse_cargo_capacity(texts)
    if capacity is None:
        all_texts = ocr_texts()
        capacity = parse_cargo_capacity(all_texts)
        if capacity is None:
            capture_state(
                "account_profile_cargo_missing",
                extra={"texts": texts[:20], "all_texts": all_texts[:40]},
            )
            capture_page_state(
                "account_profile_cargo_missing",
                extra={"texts": texts[:20], "all_texts": all_texts[:40]},
            )
    return capacity


def read_unavailable_map_cities(cities: list[str] | None = None) -> list[str] | None:
    """Open the route map and identify cities whose panel says they are unopened."""
    target_cities = [city for city in (cities or CITYS) if city]
    if not target_cities:
        return []

    emit_run_status("正在读取城市开放状态", "正在打开站点地图")
    if not go_home():
        capture_state("account_profile_unavailable_go_home_failed")
        capture_page_state("account_profile_unavailable_go_home_failed")
        return None

    open_station_map_from_home()
    unavailable: list[str] = []
    for index, city in enumerate(target_cities, start=1):
        emit_run_status(
            "正在读取城市开放状态",
            f"正在检查 {city}（{index}/{len(target_cities)}）",
            target_city=city,
        )
        try:
            probe = select_station_on_map(
                city,
                travel=False,
                reset_first=True,
                coordinate_first=True,
                route_first=True,
                fallback_scan=False,
            )
        except MapNavigationError as exc:
            logger.warning(f"检查城市开放状态失败: {city} {exc}")
            continue
        except Exception as exc:
            logger.exception(f"检查城市开放状态异常: {city} {exc}")
            continue

        if not probe:
            logger.warning(f"未能确认城市开放状态: {city}")
            continue
        panel = probe.panel
        if panel.unavailable or (
            not panel.has_travel_button and not panel.has_current_station_actions
        ):
            unavailable.append(city)

    go_home()
    emit_run_status("城市开放状态读取完成", f"未开放城市 {len(unavailable)} 个")
    return unavailable


def analyze_account_profile(
    *,
    read_cargo: bool = True,
    read_prestige: bool = True,
    read_role_resonance: bool = True,
    role_resonance_roles: list[str] | None = None,
    role_resonance_incremental: bool = False,
    role_resonance_known_roles: list[str] | None = None,
    read_unavailable_cities_flag: bool = False,
    prestige_cities: list[str] | None = None,
) -> AccountProfileResult:
    logger.info("开始读取账号配置")
    emit_run_status("正在读取账号配置", "正在连接游戏")
    if not connect():
        return AccountProfileResult(False, error="ADB连接失败")

    city_name: str | None = None
    value_by_city: dict[str, int] = {}
    prestige_by_city: dict[str, int] = {}
    cargo_capacity: int | None = None
    role_resonance: dict[str, int] = {}
    unavailable_cities: list[str] | None = None

    read_role_resonance_requested = bool(read_role_resonance)
    requested = {
        "cargo": bool(read_cargo),
        "prestige": bool(read_prestige),
        "role_resonance": read_role_resonance_requested,
        "unavailable_cities": bool(read_unavailable_cities_flag),
    }
    if not any(requested.values()):
        emit_run_status("账号配置无需读取", "当前账号配置没有缺失项")
        return AccountProfileResult(True)

    if read_prestige:
        value_by_city, prestige_by_city = read_profile_city_prestige()
        requested_cities = {
            prestige_master_city(str(city).strip())
            for city in (prestige_cities or [])
            if str(city).strip()
        }
        missing_requested = requested_cities - set(prestige_by_city)
        should_try_current_city = bool(missing_requested) or (
            not requested_cities and not prestige_by_city
        )
        if should_try_current_city:
            try:
                city_name = get_station()
            except Exception as exc:
                logger.warning(f"识别当前城市失败，跳过当前城市声望兜底: {exc}")
            if city_name:
                emit_run_status(
                    "正在读取账号配置",
                    f"当前城市：{city_name}",
                    current_city=city_name,
                )
                master_city = prestige_master_city(city_name)
                if not requested_cities or master_city in missing_requested:
                    current_level = read_current_city_prestige(city_name)
                    if current_level is not None and master_city:
                        prestige_by_city[master_city] = current_level

    if read_cargo:
        cargo_capacity = read_cargo_capacity()
    if read_role_resonance_requested:
        role_resonance = globals()["read_role_resonance"](
            role_resonance_roles,
            incremental=bool(role_resonance_incremental),
            known_roles=role_resonance_known_roles,
        )
    if read_unavailable_cities_flag:
        unavailable_cities = read_unavailable_map_cities()
    go_home()

    failed_parts: list[str] = []
    if read_prestige and not prestige_by_city:
        failed_parts.append("城市声望")
    if read_cargo and cargo_capacity is None:
        failed_parts.append("货舱上限")
    if read_role_resonance and not role_resonance:
        failed_parts.append("乘员共振")
    if read_unavailable_cities_flag and unavailable_cities is None:
        failed_parts.append("城市开放状态")
    if failed_parts and len(failed_parts) == sum(1 for value in requested.values() if value):
        return AccountProfileResult(
            False,
            city_name=city_name,
            cargo_capacity=None,
            prestige_by_city={},
            prestige_value_by_city={},
            role_resonance={},
            unavailable_cities=unavailable_cities,
            error="未能识别" + "、".join(failed_parts),
        )

    logger.info(
        "账号配置读取完成: city={} prestige_cities={} cargo={} roles={}",
        city_name,
        len(prestige_by_city),
        cargo_capacity if cargo_capacity is not None else "未知",
        len([level for level in role_resonance.values() if int(level) >= 0]),
    )
    return AccountProfileResult(
        True,
        city_name=city_name,
        cargo_capacity=cargo_capacity,
        prestige_by_city=prestige_by_city,
        prestige_value_by_city=value_by_city,
        role_resonance=role_resonance,
        unavailable_cities=unavailable_cities,
    )
