import re
import time
from dataclasses import dataclass
from typing import Any

import cv2 as cv
import numpy as np
from loguru import logger
from qfluentwidgets import qconfig

from app.common.config import cfg
from app.common.runtime_status import emit_run_status
from app.common.signal_bus import signalBus
from core.control.control import screenshot
from core.image.image import Image
from core.module.bgr import BGR
from core.preset.control import click, go_home, ocr_click, wait_gbr
from core.preset.page_state import PageKind, classify_page
from core.utils.utils import RESOURCES_PATH, read_json


@dataclass(frozen=True)
class StrengthResource:
    name: str
    restore: int
    count_config: object
    use_all_config: object
    fallback: str | None = None
    max_count: int | None = None


@dataclass(frozen=True)
class StrengthStatus:
    current: int
    total: int
    remaining: int


@dataclass(frozen=True)
class MedicineUsePlan:
    count: int
    configured_count: int | None
    inventory_count: int | None
    clear_count: int | None
    popup_max_count: int | None
    clear_config: bool = False
    use_max_then_minus: bool = False


MIN_TRADE_STRENGTH = 60
MAX_RECOVERY_ATTEMPTS = 12
MAX_USE_ALL_ATTEMPTS = 30
MAX_DRINK_ATTEMPTS = 8
DRINK_RESTORE_FATIGUE = 150
DRINK_EXCLUDED_CITIES = frozenset(("武林源",))
PRESTIGE_THRESHOLDS_PATH = RESOURCES_PATH / "goods" / "CityPrestigeThresholds2026.json"
ATTACHED_TO_CITY_PATH = RESOURCES_PATH / "goods" / "AttachedToCityData.json"

MEDICINE_RESOURCES = (
    StrengthResource("提神棒棒糖", 60, cfg.RunStrengthLollipopCount, cfg.RunStrengthLollipopUseAll, "candy"),
    StrengthResource("提神口香糖", 100, cfg.RunStrengthGumCount, cfg.RunStrengthGumUseAll),
    StrengthResource("仙人掌提神跳糖", 900, cfg.RunStrengthCactusCandyCount, cfg.RunStrengthCactusCandyUseAll),
)
TRADE_STRENGTH_STATUS_CROP = ((940, 0), (1070, 50))
STRENGTH_STATUS_CROPS = (
    TRADE_STRENGTH_STATUS_CROP,
    ((880, 305), (1190, 370)),
    ((285, 245), (505, 295)),
    ((70, 575), (250, 635)),
    ((50, 560), (245, 640)),
    ((40, 520), (260, 655)),
)
HUASHI_RESOURCE = StrengthResource("桦石", 150, cfg.RunHuashiCount, cfg.RunHuashiUseAll, max_count=8)
MEDICINE_CARD_AREAS = {
    "提神棒棒糖": ((570, 150), (750, 325)),
    "提神口香糖": ((810, 150), (990, 325)),
    "仙人掌提神跳糖": ((570, 410), (750, 585)),
}
MEDICINE_UNAVAILABLE_TEXTS = ("获取途径", "数量不足", "不足", "已用完", "无库存")
BENTO_BACK_POINT = (83, 36)
BENTO_PAGE_TITLE_TEXT = "便当柜"
BENTO_PAGE_TEXTS = ("BENTOCABINET", "BOXMEAL", "工作餐", "全部使用", "爱心便当")
BENTO_SHORTAGE_TEXTS = ("便当余量不足", "余量不足")
STRENGTH_PAGE_TEXTS = ("FATIGUE", "疲劳值", "请选择恢复疲劳值方式", "前往便当柜")
BENTO_ALL_USE_TEXTS = ("全部使用", "全都使用", "全部使")
BENTO_USE_TEXTS = ("使用",)
BENTO_AFTER_USE_CONFIRM_TEXTS = ("确定", "确认", "完成", "关闭", "知道了")
DRINK_ACTION_TEXTS = ("前往休息区", "喝一杯", "喝酒", "饮酒", "小酌")
DRINK_CONFIRM_TEXTS = ("确认", "确定", "喝一杯", "喝酒", "饮用")
DRINK_REPEAT_TEXTS = ("再喝一杯", "再来一杯")
DRINK_SKIP_TEXTS = ("SKIP", "Skip", "skip", "跳过")
DRINK_COST_CONFIRM_TEXTS = ("使用银枝", "消耗银枝", "是否使用银枝", "使用银枝气泡水", "消耗银枝气泡水")
DRINK_UNAVAILABLE_TEXTS = (
    "不在范围内",
    "今日已饮",
    "已经喝",
    "次数不足",
    "无法饮酒",
    "不可饮酒",
    "次数已用完",
    "没有可用次数",
    "今日次数已用完",
    "每日次数已用完",
)
DRINK_CROP_POS1 = (1010, 150)
DRINK_CROP_POS2 = (1210, 645)
DRINK_ENTRY_FALLBACK_POINT = (1112, 343)
REST_AREA_TEXTS = ("休息区", "喝一杯", "所有城市合计每日提供")
REST_AREA_DRINK_CROP_POS1 = (720, 260)
REST_AREA_DRINK_CROP_POS2 = (1210, 375)
DRINK_SELECT_TEXTS = ("银枝气泡水", "本次免费", "喝一杯吗")
DRINK_SELECT_CROP_POS1 = (700, 360)
DRINK_SELECT_CROP_POS2 = (1210, 470)
DRINK_SELECT_FALLBACK_POINT = (1162, 421)
DRINK_SKIP_POINT = (1218, 42)
DRINK_INFO_POINT = (1165, 285)
DRINK_INFO_CROP_POS1 = (690, 145)
DRINK_INFO_CROP_POS2 = (1260, 520)
STRENGTH_CONFIRM_TEXTS = ("确认", "确定", "补充")
MEDICINE_POPUP_TEXTS = ("请选择补充次数", "当前疲劳值", "补充后疲劳值", "持有数量", "拥有数量")
MEDICINE_MAX_TEXTS = ("最多", "最大", "MAX", "Max", "max")
MEDICINE_POPUP_PLUS_POINT = (827, 479)
MEDICINE_POPUP_MINUS_POINT = (456, 479)
MEDICINE_POPUP_MAX_POINT = (892, 479)
MEDICINE_POPUP_CONFIRM_POINT = (966, 537)
NO_REMIND_TEXTS = (
    "不再提示",
    "不再提醒",
    "不再弹出",
    "下次跳过",
    "下次不提示",
    "下次不再",
    "当天不再",
    "当日不再",
    "今日不再",
    "本日不再",
    "当周不再",
    "本周不再",
)
NO_REMIND_CROP_POS1 = (0, 330)
NO_REMIND_CROP_POS2 = (1280, 690)
BARGAIN_RESET_TEXTS = ("议价幅度将重置", "退出后议价")
BARGAIN_RESET_CANCEL_POINT = (320, 505)
HUASHI_EXHAUSTED_TEXTS = ("购买次数不足", "次数不足")
HUASHI_SHOP_PROMPT_TEXTS = ("购买次数不足", "月度商会支援礼包", "商会支援礼包", "前往购买")
HUASHI_SHOP_CANCEL_POINT = (345, 503)
HUASHI_SHOP_CANCEL_CROP_POS1 = (220, 450)
HUASHI_SHOP_CANCEL_CROP_POS2 = (460, 560)
PROFILE_ENTRY_POINT = (155, 650)
PROFILE_FATIGUE_PLUS_POINT = (467, 276)
PROFILE_CLOSE_POINT = (1000, 360)
PROFILE_PANEL_TEXTS = ("查看更多信息", "列车长形象", "营运总览", "导航手册")
TRADE_STRENGTH_ENTRY_POINT = (974, 32)
TRADE_STRENGTH_ENTRY_KINDS = (
    PageKind.BUSINESS_MENU,
    PageKind.BUY_PAGE,
    PageKind.SELL_PAGE,
    PageKind.BUY_REPORT,
    PageKind.SELL_REPORT,
)
TRADE_STRENGTH_VISIBLE_TEXTS = (
    "交易所",
    "我要买",
    "我要卖",
    "预计买入",
    "预计卖出",
    "全部买入",
    "全部卖出",
    "使用道具",
)
MAIN_MAP_TEXTS = ("访问城市", "STARTENGINE", "启程", "车厢内")
SHOP_PAGE_TEXTS = ("黑月商店", "NIGHTCHAINSSTORE", "限定服装", "总部商店", "赴命商店", "石专柜", "特惠礼包")
STRENGTH_BLOCKING_POPUP_TEXTS = ("购买礼包", "购买可获得", "立即获得", "超值月卡", "是否退出当前账号")
STRENGTH_BLOCKING_POPUP_CANCEL_POINT = (320, 503)

_DRINK_EXHAUSTED_THIS_RUN = False
_HUASHI_EXHAUSTED_THIS_RUN = False
_FOOD_UNAVAILABLE_THIS_RUN = False
_DRINK_REMAINING_THIS_RUN: int | None = None


def reset_strength_runtime_state() -> None:
    global _DRINK_EXHAUSTED_THIS_RUN, _HUASHI_EXHAUSTED_THIS_RUN, _FOOD_UNAVAILABLE_THIS_RUN
    global _DRINK_REMAINING_THIS_RUN
    _DRINK_EXHAUSTED_THIS_RUN = False
    _HUASHI_EXHAUSTED_THIS_RUN = False
    _FOOD_UNAVAILABLE_THIS_RUN = False
    _DRINK_REMAINING_THIS_RUN = None
    logger.info("已重置本轮脚本疲劳恢复渠道状态")


def _drink_supported_cities() -> frozenset[str]:
    thresholds = read_json(PRESTIGE_THRESHOLDS_PATH, {})
    attached = read_json(ATTACHED_TO_CITY_PATH, {})
    raw_cities = thresholds.get("cities", {}) if isinstance(thresholds, dict) else {}
    if not isinstance(raw_cities, dict):
        return frozenset()
    if not isinstance(attached, dict):
        attached = {}
    cities = {
        str(attached.get(str(city), city)).strip()
        for city in raw_cities.keys()
        if str(city).strip()
    }
    return frozenset(city for city in cities if city and city not in DRINK_EXCLUDED_CITIES)


def _parse_strength_text(text: str) -> tuple[int, int] | None:
    text = str(text).replace(" ", "").replace("O", "0").replace("o", "0").replace("//", "/")
    match = re.search(r"(\d{1,5})\D*/\D*(\d{1,5})", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    numbers = re.findall(r"\d{1,4}", text)
    if len(numbers) >= 2:
        return int(numbers[0]), int(numbers[1])
    return None


def _status_from_texts(texts: list[str]) -> StrengthStatus | None:
    for text in texts:
        parsed = _parse_strength_text(text)
        if not parsed:
            continue
        cur_strength, total_strength = parsed
        if total_strength <= 0:
            continue
        remaining = max(0, total_strength - cur_strength)
        return StrengthStatus(cur_strength, total_strength, remaining)

    joined = "".join(texts)
    if not joined:
        return None
    parsed = _parse_strength_text(joined)
    if not parsed:
        return None
    cur_strength, total_strength = parsed
    if total_strength <= 0:
        return None
    remaining = max(0, total_strength - cur_strength)
    return StrengthStatus(cur_strength, total_strength, remaining)


def _ocr_strength_crop(crop: cv.typing.MatLike) -> StrengthStatus | None:
    variants: list[cv.typing.MatLike] = [
        crop,
        cv.resize(crop, None, fx=3, fy=3, interpolation=cv.INTER_CUBIC),
    ]
    hsv = cv.cvtColor(crop, cv.COLOR_BGR2HSV)
    white_mask = cv.inRange(hsv, np.array([0, 0, 145]), np.array([179, 95, 255]))
    variants.append(cv.cvtColor(white_mask, cv.COLOR_GRAY2BGR))
    variants.append(cv.resize(cv.cvtColor(white_mask, cv.COLOR_GRAY2BGR), None, fx=3, fy=3, interpolation=cv.INTER_NEAREST))

    for variant in variants:
        image = Image(variant)
        texts = [str(item.get("text", "")) for item in image.ocr()]
        if status := _status_from_texts(texts):
            return status
        texts = [str(item.get("text", "")) for item in image.number_ocr()]
        if status := _status_from_texts(texts):
            return status
    return None


def _read_strength_status_from_crops(image, crops) -> StrengthStatus | None:
    raw = image.image if hasattr(image, "image") else image
    for cropped_pos1, cropped_pos2 in crops:
        x1, y1 = cropped_pos1
        x2, y2 = cropped_pos2
        crop = raw[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        if status := _ocr_strength_crop(crop):
            return status
    return None


def read_trade_header_strength_status(image=None) -> StrengthStatus | None:
    image = image or screenshot()
    return _read_strength_status_from_crops(image, (TRADE_STRENGTH_STATUS_CROP,))


def read_strength_status(image=None) -> StrengthStatus | None:
    image = image or screenshot()
    if status := _read_strength_status_from_crops(image, STRENGTH_STATUS_CROPS):
        return status
    logger.debug("当前页面未识别到疲劳值，跳过主动疲劳判断")
    return None


def wait_trade_header_strength_status(timeout: float = 1.2) -> StrengthStatus | None:
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        status = read_trade_header_strength_status()
        if status is not None:
            return status
        time.sleep(0.3)
    return None


def wait_strength_status(timeout: float = 3.0) -> StrengthStatus | None:
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        status = read_strength_status()
        if status is not None:
            return status
        time.sleep(0.3)
    return None


def has_enough_strength(required_fatigue: int = MIN_TRADE_STRENGTH, *, open_if_needed: bool = False) -> bool:
    status = wait_trade_header_strength_status(timeout=0.8)
    if status is None and _page_may_show_strength_status():
        status = wait_strength_status(timeout=1.2)
    elif open_if_needed:
        status = read_strength_status_for_check()
    if status is None:
        return True
    return status.remaining >= max(0, int(required_fatigue or 0))


def _visible_strength_status(timeout: float = 1.2) -> StrengthStatus | None:
    if not _page_may_show_strength_status():
        return None
    return wait_strength_status(timeout=timeout)


def _visible_strength_enough(required_fatigue: int = MIN_TRADE_STRENGTH) -> bool:
    status = _visible_strength_status()
    return status is not None and status.remaining >= max(0, int(required_fatigue or 0))


def check_shop_strength():
    return has_enough_strength(MIN_TRADE_STRENGTH)


def has_configured_strength_recovery() -> bool:
    if bool(cfg.RunAllowDrink.value) and not _DRINK_EXHAUSTED_THIS_RUN:
        return True
    if bool(cfg.RunAllowFood.value) and not _FOOD_UNAVAILABLE_THIS_RUN:
        return True
    if bool(cfg.RunUseStrengthMedicine.value):
        for resource in MEDICINE_RESOURCES:
            if _resource_available(resource):
                return True
    if bool(cfg.RunUseHuashi.value) and not _HUASHI_EXHAUSTED_THIS_RUN and _resource_available(HUASHI_RESOURCE):
        return True
    return False


def _resource_available(resource: StrengthResource) -> bool:
    if bool(resource.use_all_config.value):
        return True
    count = int(resource.count_config.value or 0)
    if resource.max_count is not None:
        count = min(count, resource.max_count)
    return count > 0


def _set_resource_count(resource: StrengthResource, count: int) -> None:
    count = max(0, int(count or 0))
    qconfig.set(resource.count_config, count)
    signalBus.fatigueResourceCountChanged.emit(resource.count_config, count)


def _consume_resource_count(resource: StrengthResource, amount: int = 1) -> None:
    if bool(resource.use_all_config.value):
        return
    current_count = int(resource.count_config.value or 0)
    if resource.max_count is not None:
        current_count = min(current_count, resource.max_count)
    count = max(0, current_count - max(1, int(amount or 1)))
    _set_resource_count(resource, count)
    logger.info(f"{resource.name} 使用数量已扣减，剩余配置数量: {count}")


def _huashi_daily_remaining(texts: list[str]) -> int | None:
    joined = "".join(texts).replace(" ", "").replace("O", "0").replace("o", "0")
    match = re.search(r"(?:每日)?限购(\d+)\s*/\s*8", joined)
    if not match:
        return None
    return int(match.group(1))


def _has_huashi_shop_prompt(texts: list[str] | None = None) -> bool:
    items = texts if texts is not None else _current_clean_texts()
    return any(keyword in text for keyword in HUASHI_SHOP_PROMPT_TEXTS for text in items)


def _mark_drink_exhausted(reason: str = "") -> None:
    global _DRINK_EXHAUSTED_THIS_RUN, _DRINK_REMAINING_THIS_RUN
    _DRINK_EXHAUSTED_THIS_RUN = True
    _DRINK_REMAINING_THIS_RUN = 0
    logger.info(f"喝酒次数已确认耗尽，本轮脚本不再尝试喝酒{f': {reason}' if reason else ''}")


def _mark_food_unavailable(reason: str = "") -> None:
    global _FOOD_UNAVAILABLE_THIS_RUN
    _FOOD_UNAVAILABLE_THIS_RUN = True
    logger.info(f"便当已确认不可用，本轮脚本不再尝试便当{f': {reason}' if reason else ''}")


def _mark_huashi_exhausted() -> None:
    global _HUASHI_EXHAUSTED_THIS_RUN
    _HUASHI_EXHAUSTED_THIS_RUN = True
    _set_resource_count(HUASHI_RESOURCE, 0)
    if bool(HUASHI_RESOURCE.use_all_config.value):
        qconfig.set(HUASHI_RESOURCE.use_all_config, False)
    logger.warning("桦石今日恢复次数已耗尽，本轮脚本不再尝试桦石，并已将使用数量同步为 0")


def _dismiss_huashi_shop_prompt(texts: list[str] | None = None) -> bool:
    if not _has_huashi_shop_prompt(texts):
        return False
    _mark_huashi_exhausted()
    logger.warning("检测到桦石购买次数不足弹窗，取消前往商城")
    for _ in range(3):
        if not _ocr_tap_any(
            ("取消",),
            cropped_pos1=HUASHI_SHOP_CANCEL_CROP_POS1,
            cropped_pos2=HUASHI_SHOP_CANCEL_CROP_POS2,
            exact=False,
        ):
            click(HUASHI_SHOP_CANCEL_POINT)
        time.sleep(0.8)
        if not _has_huashi_shop_prompt():
            return True
    return False


def _huashi_exhausted() -> bool:
    texts = _current_clean_texts()
    remaining = _huashi_daily_remaining(texts)
    if remaining == 0 or any(keyword in text for keyword in HUASHI_EXHAUSTED_TEXTS for text in texts):
        if not _dismiss_huashi_shop_prompt(texts):
            _mark_huashi_exhausted()
        return True
    return False


def _huashi_purchase_notice() -> str | None:
    image = screenshot()
    texts = [str(item.get("text", "")) for item in image.ocr()]
    joined = "".join(texts).replace(" ", "").replace("，", ",").replace("。", ".")
    match = re.search(r"消耗[^\d]*(\d+).*?桦石.*?(?:消除|恢复)[^\d]*(\d+).*?疲劳", joined)
    if match:
        return f"本次消耗 {match.group(1)} 桦石，恢复 {match.group(2)} 疲劳"
    if "桦石" in joined and "疲劳" in joined:
        return "确认弹窗已显示本次桦石消耗"
    return None


def _wait_huashi_purchase_notice(timeout: float = 5.0) -> str | None:
    start = time.perf_counter()
    fallback: str | None = None
    while time.perf_counter() - start < timeout:
        if _dismiss_huashi_shop_prompt():
            return None
        notice = _huashi_purchase_notice()
        if notice:
            if "本次消耗" in notice:
                return notice
            fallback = notice
        time.sleep(0.4)
    return fallback


def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.4) -> bool:
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _is_profile_panel(texts: list[str] | None = None) -> bool:
    items = texts if texts is not None else _current_clean_texts()
    return any(keyword in text for keyword in PROFILE_PANEL_TEXTS for text in items)


def _is_main_map(texts: list[str] | None = None) -> bool:
    items = texts if texts is not None else _current_clean_texts()
    return any(keyword in text for keyword in MAIN_MAP_TEXTS for text in items)


def _is_shop_page(texts: list[str] | None = None) -> bool:
    items = texts if texts is not None else _current_clean_texts()
    return any(keyword in text for keyword in SHOP_PAGE_TEXTS for text in items)


def _is_trade_page_from_texts(texts: list[str] | None = None) -> bool:
    items = texts if texts is not None else _current_clean_texts()
    return any(keyword in text for keyword in TRADE_STRENGTH_VISIBLE_TEXTS for text in items)


def _page_may_show_strength_status(texts: list[str] | None = None) -> bool:
    items = texts if texts is not None else _current_clean_texts()
    return _is_strength_page_from_texts(items) or _is_profile_panel(items) or _is_trade_page_from_texts(items)


def _close_profile_panel() -> bool:
    for _ in range(3):
        if not _is_profile_panel():
            return True
        click(PROFILE_CLOSE_POINT)
        time.sleep(0.8)
    return not _is_profile_panel()


def _open_profile_panel_from_main() -> bool:
    texts = _current_clean_texts()
    if _is_profile_panel(texts):
        return True
    if _is_shop_page(texts):
        logger.warning("当前在商城页面，先返回主界面再打开疲劳页")
        if not go_home():
            return False
        texts = _current_clean_texts()
    if not _is_main_map(texts):
        logger.debug("当前不在主界面，先返回主界面再打开个人信息疲劳入口")
        if not go_home():
            return False
    click(PROFILE_ENTRY_POINT)
    return _wait_until(_is_profile_panel, timeout=4.0)


def _open_strength_page_from_trade() -> bool:
    state = classify_page()
    if state.kind not in TRADE_STRENGTH_ENTRY_KINDS:
        return False
    logger.info(f"当前在 {state.kind.value}，优先从交易页顶部疲劳入口打开疲劳页")
    click(TRADE_STRENGTH_ENTRY_POINT)
    if _wait_until(_is_strength_page, timeout=4.0):
        return True
    logger.warning("交易页顶部疲劳入口未能打开疲劳页面")
    return False


def open_strength_page() -> bool:
    if _is_strength_page():
        return True
    if _open_strength_page_from_trade():
        return True
    if not _open_profile_panel_from_main():
        logger.warning("未能打开个人信息面板，无法进入疲劳页面")
        return False
    click(PROFILE_FATIGUE_PLUS_POINT)
    if _wait_until(_is_strength_page, timeout=5.0):
        return True
    logger.warning("个人信息面板中未能打开疲劳页面")
    _close_profile_panel()
    return False


def _is_bento_page() -> bool:
    image = screenshot()
    texts = [str(item.get("text", "")).replace(" ", "") for item in image.ocr()]
    return any(text == BENTO_PAGE_TITLE_TEXT for text in texts) or any(
        keyword in text for keyword in BENTO_PAGE_TEXTS for text in texts
    )


def _is_rest_area_page(texts: list[str] | None = None) -> bool:
    items = texts if texts is not None else _current_clean_texts()
    return any(keyword in text for keyword in REST_AREA_TEXTS for text in items)


def _is_drink_select_page(texts: list[str] | None = None) -> bool:
    items = texts if texts is not None else _current_clean_texts()
    return any(keyword in text for keyword in DRINK_SELECT_TEXTS for text in items)


def _is_strength_page() -> bool:
    image = screenshot()
    texts = [str(item.get("text", "")).replace(" ", "") for item in image.ocr()]
    return _is_strength_page_from_texts(texts)


def _is_strength_page_from_texts(texts: list[str]) -> bool:
    joined = "".join(texts)
    if "请选择恢复疲劳值方式" in joined or "前往便当柜" in joined:
        return True
    has_title = any(keyword in text for keyword in ("FATIGUE", "疲劳值") for text in texts)
    has_recovery_option = any(
        keyword in text
        for keyword in (
            "便当柜",
            "休息区",
            "使用体力药",
            "提神棒棒糖",
            "提神口香糖",
            "仙人掌提神跳糖",
            "桦石",
        )
        for text in texts
    )
    return has_title and has_recovery_option


def _current_clean_texts() -> list[str]:
    return [str(item.get("text", "")).replace(" ", "") for item in screenshot().ocr()]


def _has_any_clean_text(keywords: tuple[str, ...], texts: list[str] | None = None) -> bool:
    items = texts if texts is not None else _current_clean_texts()
    return any(keyword in text for keyword in keywords for text in items)


def _has_bargain_reset_warning() -> bool:
    return _has_any_clean_text(BARGAIN_RESET_TEXTS)


def _dismiss_bargain_reset_warning() -> bool:
    if not _has_bargain_reset_warning():
        return False
    logger.warning("检测到议价退出重置提示，取消退出并保留当前交易流程")
    if not _ocr_tap_any(("取消",), cropped_pos1=(230, 455), cropped_pos2=(430, 550), exact=False):
        click(BARGAIN_RESET_CANCEL_POINT)
    time.sleep(0.8)
    return True


def _dismiss_strength_blocking_popup() -> bool:
    if not _has_any_clean_text(STRENGTH_BLOCKING_POPUP_TEXTS):
        return False
    logger.warning("检测到疲劳/个人信息阻塞弹窗，点击取消")
    if not _ocr_tap_any(("取消",), cropped_pos1=(0, 450), cropped_pos2=(650, 560), exact=False):
        click(STRENGTH_BLOCKING_POPUP_CANCEL_POINT)
    time.sleep(0.8)
    return True


def _leave_bento_page() -> bool:
    for _ in range(3):
        if not _is_bento_page():
            return True
        click(BENTO_BACK_POINT)
        time.sleep(0.8)
    return not _is_bento_page()


def _leave_rest_area_page() -> bool:
    for _ in range(3):
        if not _is_rest_area_page() and not _is_drink_select_page():
            return True
        click(BENTO_BACK_POINT)
        time.sleep(1.2)
    return not _is_rest_area_page() and not _is_drink_select_page()


def close_strength_page() -> bool:
    if _is_rest_area_page() and not _leave_rest_area_page():
        return False
    if _is_bento_page() and not _leave_bento_page():
        return False
    for _ in range(3):
        if _is_rest_area_page():
            if not _leave_rest_area_page():
                return False
            continue
        if _dismiss_huashi_shop_prompt():
            continue
        if _dismiss_strength_blocking_popup():
            continue
        if _dismiss_bargain_reset_warning():
            return True
        if not _is_strength_page():
            if _is_profile_panel():
                return _close_profile_panel()
            return True
        click(BENTO_BACK_POINT)
        time.sleep(0.8)
    if _dismiss_huashi_shop_prompt():
        return close_strength_page()
    if _dismiss_strength_blocking_popup():
        return close_strength_page()
    if _dismiss_bargain_reset_warning():
        return True
    if _is_profile_panel():
        return _close_profile_panel()
    return not _is_strength_page()


def _wait_bento_page(timeout: float = 5.0) -> bool:
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        if _is_bento_page():
            return True
        time.sleep(0.4)
    return False


def _ocr_tap_any(
    texts: tuple[str, ...],
    *,
    cropped_pos1: tuple[int, int] = (0, 0),
    cropped_pos2: tuple[int, int] = (0, 0),
    exact: bool = False,
) -> bool:
    image = screenshot()
    image.crop_image(cropped_pos1, cropped_pos2)
    for item in image.ocr():
        text = str(item.get("text", "")).replace(" ", "")
        for target in texts:
            if (exact and text != target) or (not exact and target not in text):
                continue
            position = item["position"]
            center_x = int((position[0][0] + position[2][0]) / 2)
            center_y = int((position[0][1] + position[2][1]) / 2)
            logger.debug(f"点击文本 {text} => ({center_x}, {center_y})")
            click((center_x, center_y))
            return True
    return False


def _tap_bento_use_button() -> bool:
    image = screenshot()
    image.crop_image((780, 365), (1180, 470))
    ocr_items = list(image.ocr())

    def item_center(item) -> tuple[int, int]:
        position = item["position"]
        center_x = int((position[0][0] + position[2][0]) / 2)
        center_y = int((position[0][1] + position[2][1]) / 2)
        return center_x, center_y

    def tap_item(item, reason: str) -> bool:
        center_x, center_y = item_center(item)
        logger.debug(f"点击便当{reason}按钮 {item.get('text', '')} => ({center_x}, {center_y})")
        click((center_x, center_y))
        return True

    for item in ocr_items:
        text = str(item.get("text", "")).replace(" ", "")
        if any(target in text for target in BENTO_ALL_USE_TEXTS):
            return tap_item(item, "全部使用")

    all_text_items = []
    use_text_items = []
    for item in ocr_items:
        text = str(item.get("text", "")).replace(" ", "")
        if "全部" in text or "全都" in text:
            all_text_items.append(item)
        if "使用" in text:
            use_text_items.append(item)

    for all_item in all_text_items:
        all_x, all_y = item_center(all_item)
        same_button_uses = []
        for use_item in use_text_items:
            use_x, use_y = item_center(use_item)
            if use_x >= all_x and abs(use_y - all_y) <= 32:
                same_button_uses.append((use_x - all_x, use_item))
        if same_button_uses:
            return tap_item(sorted(same_button_uses, key=lambda item: item[0])[0][1], "全部使用")

    if _ocr_tap_any(
        BENTO_USE_TEXTS,
        cropped_pos1=(780, 365),
        cropped_pos2=(1180, 470),
        exact=False,
    ):
        logger.warning("便当页面未识别到全部使用按钮，已降级点击普通使用")
        return True

    return False


def _tap_no_remind_checkbox_if_present() -> bool:
    image = screenshot()
    image.crop_image(NO_REMIND_CROP_POS1, NO_REMIND_CROP_POS2)
    for item in image.ocr():
        text = str(item.get("text", "")).replace(" ", "")
        if not _is_no_remind_text(text):
            continue
        position = item["position"]
        left_x = int(min(point[0] for point in position))
        center_y = int((position[0][1] + position[2][1]) / 2)
        checkbox_pos = _find_checkbox_left_of_text(screenshot(), left_x, center_y)
        click(checkbox_pos)
        logger.info(f"已勾选弹窗选项: {text}")
        time.sleep(0.25)
        return True
    return False


def _is_no_remind_text(text: str) -> bool:
    compact = str(text).replace(" ", "")
    if any(keyword in compact for keyword in NO_REMIND_TEXTS):
        return True
    return "不再" in compact and any(keyword in compact for keyword in ("提示", "提醒", "弹", "显示"))


def _find_checkbox_left_of_text(image, text_left_x: int, text_center_y: int) -> tuple[int, int]:
    raw = image.image if hasattr(image, "image") else image
    y1 = max(0, text_center_y - 24)
    y2 = min(raw.shape[0], text_center_y + 24)
    x1 = max(0, text_left_x - 130)
    x2 = max(0, text_left_x - 4)
    crop = raw[y1:y2, x1:x2]
    if crop.size:
        gray = cv.cvtColor(crop, cv.COLOR_BGR2GRAY)
        edges = cv.Canny(gray, 50, 160)
        contours, _ = cv.findContours(edges, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        candidates: list[tuple[int, int, int, int]] = []
        for contour in contours:
            x, y, w, h = cv.boundingRect(contour)
            if 10 <= w <= 32 and 10 <= h <= 32 and abs(w - h) <= 8:
                candidates.append((x, y, w, h))
        if candidates:
            x, y, w, h = sorted(candidates, key=lambda rect: abs((y1 + rect[1] + rect[3] // 2) - text_center_y))[0]
            return (x1 + x + w // 2, y1 + y + h // 2)
    return (max(24, text_left_x - 52), text_center_y)


def _tap_popup_action(
    texts: tuple[str, ...],
    *,
    cropped_pos1: tuple[int, int] = (0, 0),
    cropped_pos2: tuple[int, int] = (0, 0),
    exact: bool = False,
) -> bool:
    _tap_no_remind_checkbox_if_present()
    return _ocr_tap_any(texts, cropped_pos1=cropped_pos1, cropped_pos2=cropped_pos2, exact=exact)


def _dismiss_bento_after_use_prompt(timeout: float = 4.0) -> bool:
    dismissed = False
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        texts = _current_clean_texts()
        has_confirm = any(keyword in text for keyword in BENTO_AFTER_USE_CONFIRM_TEXTS for text in texts)
        if _is_strength_page_from_texts(texts):
            return dismissed
        if any(keyword in text for keyword in BENTO_PAGE_TEXTS for text in texts) and not has_confirm:
            return dismissed
        if _tap_popup_action(
            BENTO_AFTER_USE_CONFIRM_TEXTS,
            cropped_pos1=(540, 360),
            cropped_pos2=(1160, 690),
            exact=False,
        ):
            dismissed = True
            time.sleep(0.8)
            continue
        time.sleep(0.4)
    return dismissed


def _has_drink_cost_confirm(texts: list[str] | None = None) -> bool:
    items = texts if texts is not None else _current_clean_texts()
    joined = "".join(items)
    return any(keyword in joined for keyword in DRINK_COST_CONFIRM_TEXTS) or ("银枝气泡水" in joined and "使用" in joined)


def _dismiss_drink_cost_confirm(texts: list[str] | None = None) -> bool:
    if not _has_drink_cost_confirm(texts):
        return False
    _mark_drink_exhausted("检测到银枝气泡水消耗确认")
    if not _ocr_tap_any(("取消",), cropped_pos1=(170, 420), cropped_pos2=(520, 650), exact=False):
        click((320, 503))
    time.sleep(0.8)
    return True


def use_food():
    if _FOOD_UNAVAILABLE_THIS_RUN:
        logger.info("本轮脚本已确认便当不可用，跳过便当恢复")
        return False
    if not _ensure_strength_page_for_recovery("使用便当"):
        return False
    before = read_strength_status()
    if any(keyword in text for keyword in BENTO_SHORTAGE_TEXTS for text in _current_clean_texts()):
        _mark_food_unavailable("疲劳页提示便当余量不足")
        logger.warning("当前便当余量不足，跳过便当恢复")
        return False
    if not ocr_click(
        "前往便当柜",
        cropped_pos1=(1020, 560),
        cropped_pos2=(1205, 645),
        trynum=2,
        log=False,
    ):
        _mark_food_unavailable("疲劳页未识别到便当入口")
        logger.warning("疲劳页未找到便当入口，跳过便当恢复")
        return False
    if not _wait_bento_page():
        texts = _current_clean_texts()
        if any(keyword in text for keyword in BENTO_SHORTAGE_TEXTS for text in texts):
            _mark_food_unavailable("进入便当柜时提示余量不足")
            logger.warning("当前便当余量不足，无法进入便当柜恢复")
        else:
            logger.error("未找到便当页面")
        return False

    try:
        if not _tap_bento_use_button():
            logger.warning("便当页面未找到使用按钮")
            return False
        time.sleep(0.8)
        confirmed = _tap_popup_action(
            STRENGTH_CONFIRM_TEXTS,
            cropped_pos1=(880, 450),
            cropped_pos2=(1080, 640),
            exact=False,
        )
        time.sleep(1.0)
        if confirmed:
            _dismiss_bento_after_use_prompt()
        if _is_bento_page():
            _leave_bento_page()
        after = wait_strength_status(timeout=2.5)
        if before and after and after.remaining > before.remaining:
            logger.info(f"已使用便当恢复疲劳: {before.remaining}->{after.remaining}")
            return True
        if before is None and after and after.remaining > 0:
            logger.info("已使用便当恢复疲劳")
            return True
        if confirmed:
            logger.info("已确认使用便当，但未能读取疲劳变化，按已使用便当处理")
            return True
        texts = [str(item.get("text", "")).replace(" ", "") for item in screenshot().ocr()]
        if any(keyword in text for keyword in BENTO_SHORTAGE_TEXTS for text in texts):
            logger.warning("当前便当余量不足，跳过便当恢复")
        else:
            logger.warning("便当使用后疲劳值未变化")
        return False
    finally:
        if not _leave_bento_page():
            logger.warning("未能离开便当柜页面")


def use_candy():
    click((655, 242))
    return ocr_click("补充", cropped_pos1=(952, 565), cropped_pos2=(1023, 602))


def _wait_medicine_popup(resource: StrengthResource, timeout: float = 3.0) -> bool:
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        texts = _current_clean_texts()
        joined = "".join(texts)
        if resource.name in joined and any(keyword in joined for keyword in ("补充", "持有数量", "拥有数量", "当前疲劳")):
            return True
        if any(keyword in joined for keyword in MEDICINE_POPUP_TEXTS) and "补充" in joined:
            return True
        time.sleep(0.25)
    return False


def _parse_inventory_count_from_texts(texts: list[str]) -> int | None:
    candidates = [str(text or "").replace(" ", "").replace("O", "0").replace("o", "0") for text in texts]
    for index, text in enumerate(candidates):
        if not any(keyword in text for keyword in ("持有数量", "拥有数量", "持有数", "拥有数", "持有", "拥有")):
            continue
        window = "|".join(candidates[index : index + 3])
        label_match = re.search(r"(?:持有数量|拥有数量|持有数|拥有数|持有|拥有)[:：]?\D*(\d{1,4})", window)
        if label_match:
            return int(label_match.group(1))
        numbers = [int(value) for value in re.findall(r"\d{1,4}", window)]
        if numbers:
            return numbers[0]
    return None


def _configured_medicine_limit(resource: StrengthResource, inventory_count: int | None, clear_count: int | None) -> int:
    if bool(resource.use_all_config.value):
        if inventory_count is not None:
            return max(0, inventory_count)
        if clear_count is not None:
            return max(1, clear_count)
        return 1
    return max(0, int(resource.count_config.value or 0))


def _calculate_medicine_use_plan(resource: StrengthResource, status: StrengthStatus | None, texts: list[str]) -> MedicineUsePlan:
    inventory_count = _parse_inventory_count_from_texts(texts)
    clear_count = None
    if status is not None and status.current > 0 and resource.restore > 0:
        clear_count = (status.current + resource.restore - 1) // resource.restore
    configured_count = _configured_medicine_limit(resource, inventory_count, clear_count)

    if configured_count <= 0:
        return MedicineUsePlan(0, configured_count, inventory_count, clear_count, None)

    inventory_shortage = False
    if inventory_count is not None and configured_count > inventory_count:
        count = inventory_count
        inventory_shortage = True
    else:
        count = configured_count

    use_max_then_minus = False
    if clear_count is not None and 0 < clear_count < configured_count:
        if inventory_count is None or inventory_count >= clear_count:
            count = clear_count - 1
            use_max_then_minus = True
        else:
            count = inventory_count

    if resource.restore >= 900 and clear_count is not None and 0 < clear_count < configured_count:
        count = max(1, count)

    if inventory_count is not None:
        count = min(count, inventory_count)
    clear_config = bool(inventory_shortage and inventory_count is not None and count >= inventory_count)

    popup_max_count = None
    if clear_count is not None and inventory_count is not None:
        popup_max_count = min(clear_count, inventory_count)
    elif clear_count is not None:
        popup_max_count = clear_count
    elif inventory_count is not None:
        popup_max_count = inventory_count

    return MedicineUsePlan(
        max(0, int(count or 0)),
        configured_count,
        inventory_count,
        clear_count,
        popup_max_count,
        clear_config=clear_config,
        use_max_then_minus=use_max_then_minus,
    )


def _tap_medicine_popup_max() -> bool:
    if _ocr_tap_any(MEDICINE_MAX_TEXTS, cropped_pos1=(560, 430), cropped_pos2=(930, 525), exact=False):
        return True
    click(MEDICINE_POPUP_MAX_POINT)
    time.sleep(0.2)
    return True


def _adjust_medicine_popup_count(plan: MedicineUsePlan) -> None:
    target = max(1, int(plan.count or 1))
    popup_max = plan.popup_max_count if plan.popup_max_count and plan.popup_max_count > 0 else None

    if popup_max is not None and target >= popup_max:
        _tap_medicine_popup_max()
        return

    if plan.use_max_then_minus and popup_max is not None and target == popup_max - 1:
        _tap_medicine_popup_max()
        click(MEDICINE_POPUP_MINUS_POINT)
        time.sleep(0.15)
        return

    if popup_max is not None and popup_max - target < target - 1:
        _tap_medicine_popup_max()
        for _ in range(max(0, popup_max - target)):
            click(MEDICINE_POPUP_MINUS_POINT)
            time.sleep(0.12)
        return

    for _ in range(max(0, target - 1)):
        click(MEDICINE_POPUP_PLUS_POINT)
        time.sleep(0.12)


def _tap_medicine_popup_confirm() -> bool:
    if _tap_popup_action(("补充",), cropped_pos1=(880, 500), cropped_pos2=(1080, 640), exact=False):
        return True
    click(MEDICINE_POPUP_CONFIRM_POINT)
    time.sleep(0.5)
    return True


def _use_medicine_resource(resource: StrengthResource) -> tuple[bool, int]:
    before = wait_strength_status(timeout=1.5)
    if resource.fallback == "candy":
        click((655, 242))
    else:
        if not ocr_click(resource.name, cropped_pos1=(430, 90), cropped_pos2=(1120, 620), log=False):
            return False, 0

    if not _wait_medicine_popup(resource):
        logger.warning(f"未识别到 {resource.name} 使用数量弹窗")
        return False, 0

    texts = _current_clean_texts()
    plan = _calculate_medicine_use_plan(resource, before, texts)
    logger.info(
        f"{resource.name} 数量计划: 配置={plan.configured_count}, 库存={plan.inventory_count}, "
        f"清空疲劳需={plan.clear_count}, 弹窗最多={plan.popup_max_count}, 实际使用={plan.count}"
    )
    if plan.count <= 0:
        logger.info(f"{resource.name} 本次计算无需使用，取消弹窗")
        if not _ocr_tap_any(("取消",), cropped_pos1=(170, 500), cropped_pos2=(520, 640), exact=False):
            click((320, 585))
        return False, 0

    _adjust_medicine_popup_count(plan)
    if not _tap_medicine_popup_confirm():
        return False, 0
    if plan.clear_config:
        _set_resource_count(resource, 0)
    return True, plan.count


def _medicine_ui_available(resource: StrengthResource) -> bool:
    area = MEDICINE_CARD_AREAS.get(resource.name)
    if not area:
        return True
    image = screenshot()
    image.crop_image(*area)
    texts = [str(item.get("text", "")).replace(" ", "") for item in image.ocr()]
    if any(keyword in text for keyword in MEDICINE_UNAVAILABLE_TEXTS for text in texts):
        logger.info(f"{resource.name} 卡片显示不可用: {texts}")
        _set_resource_count(resource, 0)
        return False
    if any(text == "0" for text in texts):
        logger.info(f"{resource.name} 卡片数量为 0，跳过")
        _set_resource_count(resource, 0)
        return False
    return True


def use_named_strength_resource(resource: StrengthResource) -> bool:
    if not _resource_available(resource):
        return False
    if resource.name == "桦石" and _HUASHI_EXHAUSTED_THIS_RUN:
        logger.info("本轮脚本已确认桦石次数耗尽，跳过桦石恢复")
        return False
    if resource.name != "桦石" and not _medicine_ui_available(resource):
        return False
    emit_run_status("正在恢复疲劳", f"尝试使用 {resource.name}（{resource.restore}疲劳）")
    used_count = 1
    if resource.name != "桦石":
        ok, used_count = _use_medicine_resource(resource)
    else:
        if _huashi_exhausted():
            return False
        ok = _ocr_tap_any(
            ("桦石",),
            cropped_pos1=(760, 420),
            cropped_pos2=(1000, 655),
            exact=False,
        )
        if not ok:
            click((902, 612))
            ok = True
        if ok:
            huashi_notice = _wait_huashi_purchase_notice()
            if not huashi_notice or "本次消耗" not in huashi_notice:
                _huashi_exhausted()
                logger.warning("未识别到桦石恢复确认弹窗的具体消耗，取消本次桦石使用")
                if not _dismiss_huashi_shop_prompt():
                    if not _ocr_tap_any(
                        ("取消",),
                        cropped_pos1=(220, 450),
                        cropped_pos2=(440, 640),
                        exact=False,
                    ):
                        click(HUASHI_SHOP_CANCEL_POINT)
                    time.sleep(0.8)
                return False
            emit_run_status(
                "正在恢复疲劳",
                huashi_notice,
            )
            logger.info(f"桦石恢复确认: {huashi_notice}")
            ok = _tap_popup_action(
                ("补充",),
                cropped_pos1=(900, 520),
                cropped_pos2=(1060, 630),
                exact=False,
            )
            if not ok:
                ok = _tap_popup_action(
                    ("确认", "确定"),
                    cropped_pos1=(880, 450),
                    cropped_pos2=(1080, 640),
                    exact=False,
                )
    if ok:
        _consume_resource_count(resource, used_count)
        logger.info(f"已使用疲劳恢复资源: {resource.name}")
    return ok


def use_huashi() -> bool:
    return use_named_strength_resource(HUASHI_RESOURCE)


def is_drink_supported_city(city_name: str | None) -> bool:
    return str(city_name or "").strip() in _drink_supported_cities()


def should_use_drink_now(min_used_fatigue: int = DRINK_RESTORE_FATIGUE) -> bool:
    status = wait_strength_status()
    if status is None:
        logger.debug("未识别到当前疲劳值，跳过主动喝酒判断")
        return False
    if status.current < max(1, int(min_used_fatigue or 0)):
        logger.info(
            f"当前已积累疲劳 {status.current}，不足一次喝酒恢复量 {min_used_fatigue}，暂不喝酒"
        )
        return False
    return True


def _tap_drink_entry() -> bool:
    texts = _current_clean_texts()
    if _is_drink_select_page(texts):
        return True
    if _has_any_clean_text(DRINK_UNAVAILABLE_TEXTS, texts):
        logger.info("当前城市或状态不支持喝酒恢复，跳过")
        return False
    if _ocr_tap_any(DRINK_ACTION_TEXTS, cropped_pos1=DRINK_CROP_POS1, cropped_pos2=DRINK_CROP_POS2):
        return True
    if _ocr_tap_any(DRINK_ACTION_TEXTS):
        return True
    if _is_strength_page():
        click(DRINK_ENTRY_FALLBACK_POINT)
        return True
    return False


def _normalize_count_text(text: str) -> str:
    return str(text or "").replace(" ", "").replace("O", "0").replace("o", "0")


def _parse_drink_remaining(texts: list[str]) -> int | None:
    candidates = [_normalize_count_text(text) for text in texts]
    joined = "".join(candidates)
    separated = "|".join(candidates)

    def parse_free_count_ratio(text: str) -> int | None:
        for match in re.finditer(r"(\d{1,2})/(\d{1,2})", text):
            current = int(match.group(1))
            total = int(match.group(2))
            if total == 6 and 0 <= current <= total:
                return current
        return None

    for index, text in enumerate(candidates):
        if any(keyword in text for keyword in ("免材料", "材料次数", "次数")):
            window = "|".join(candidates[index : index + 4])
            ratio_remaining = parse_free_count_ratio(window)
            if ratio_remaining is not None:
                return ratio_remaining

    if any(keyword in joined for keyword in ("银枝气泡水", "免材料", "材料次数")):
        ratio_remaining = parse_free_count_ratio(separated)
        if ratio_remaining is not None:
            return ratio_remaining

    patterns = (
        r"(?:剩余|还可|可用|可喝|还能喝|剩余次数|剩余可用)[^\d]{0,8}(\d{1,2})",
        r"(\d{1,2})[^\d]{0,4}(?:次|杯)[^\d]{0,8}(?:剩余|可用|还可)",
    )
    for text in (*candidates, joined):
        if "每日提供" in text and not any(keyword in text for keyword in ("剩余", "还可", "可用", "可喝", "还能")):
            continue
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return max(0, min(8, int(match.group(1))))
    for text in candidates:
        if any(keyword in text for keyword in ("剩余", "还可", "可用", "可喝", "还能")):
            numbers = [int(value) for value in re.findall(r"\d{1,2}", text)]
            if numbers:
                return max(0, min(8, numbers[0]))
    return None


def _read_drink_remaining_from_info() -> int | None:
    if not _is_strength_page():
        return None
    click(DRINK_INFO_POINT)
    time.sleep(0.8)
    image = screenshot()
    image.crop_image(DRINK_INFO_CROP_POS1, DRINK_INFO_CROP_POS2)
    texts = [str(item.get("text", "")).replace(" ", "") for item in image.ocr()]
    remaining = _parse_drink_remaining(texts)
    logger.info(f"喝酒叹号说明 OCR: {texts[:12]}，解析剩余次数: {remaining}")
    click(DRINK_INFO_POINT)
    time.sleep(0.4)
    return remaining


def _drink_remaining_before_entry() -> int | None:
    global _DRINK_REMAINING_THIS_RUN
    if _DRINK_REMAINING_THIS_RUN == 0:
        return 0
    remaining = _read_drink_remaining_from_info()
    if remaining is not None:
        _DRINK_REMAINING_THIS_RUN = remaining
        if remaining <= 0:
            _mark_drink_exhausted("叹号说明显示剩余 0 次")
    return remaining


def _tap_rest_area_drink_button() -> bool:
    ok = _ocr_tap_any(
        ("喝一杯",),
        cropped_pos1=REST_AREA_DRINK_CROP_POS1,
        cropped_pos2=REST_AREA_DRINK_CROP_POS2,
        exact=False,
    )
    if ok:
        return True
    if _is_rest_area_page():
        click((1162, 325))
        return True
    return False


def _tap_drink_choice() -> bool:
    ok = _ocr_tap_any(
        ("银枝气泡水",),
        cropped_pos1=DRINK_SELECT_CROP_POS1,
        cropped_pos2=DRINK_SELECT_CROP_POS2,
        exact=False,
    )
    if not ok:
        click(DRINK_SELECT_FALLBACK_POINT)
        ok = True
    time.sleep(0.8)
    texts = _current_clean_texts()
    if _is_drink_select_page(texts) and _has_any_clean_text(("银枝气泡水",), texts):
        click(DRINK_SELECT_FALLBACK_POINT)
        time.sleep(0.8)
    return ok


def _tap_drink_repeat_button() -> bool:
    return _tap_popup_action(
        DRINK_REPEAT_TEXTS,
        cropped_pos1=(620, 360),
        cropped_pos2=(1260, 690),
        exact=False,
    )


def _finish_drink_animation_and_result(timeout: float = 14.0) -> bool:
    start = time.perf_counter()
    skip_fallback_clicked = False
    saw_result_progress = False
    while time.perf_counter() - start < timeout:
        texts = _current_clean_texts()
        if _dismiss_drink_cost_confirm(texts):
            return False
        if _has_any_clean_text(DRINK_UNAVAILABLE_TEXTS, texts):
            return False
        if _is_drink_select_page(texts) and time.perf_counter() - start > 2.0:
            return saw_result_progress
        if (
            _has_any_clean_text(DRINK_REPEAT_TEXTS, texts)
            or (_is_rest_area_page(texts) and not _is_drink_select_page(texts))
            or (_is_strength_page_from_texts(texts) and not _is_drink_select_page(texts))
            or _is_profile_panel(texts)
        ):
            return True

        if _ocr_tap_any(
            DRINK_SKIP_TEXTS,
            cropped_pos1=(1060, 0),
            cropped_pos2=(1275, 105),
            exact=False,
        ):
            saw_result_progress = True
            time.sleep(0.8)
            continue
        if not skip_fallback_clicked and time.perf_counter() - start > 2.0:
            click(DRINK_SKIP_POINT)
            skip_fallback_clicked = True
            saw_result_progress = True
            time.sleep(0.8)
            continue
        if _tap_popup_action(
            ("确定", "确认"),
            cropped_pos1=(620, 380),
            cropped_pos2=(1260, 690),
            exact=False,
        ):
            saw_result_progress = True
            time.sleep(0.8)
            continue
        time.sleep(0.55)
    logger.warning("喝酒演出或结算确认等待超时")
    return False


def use_drink_if_available() -> bool:
    global _DRINK_REMAINING_THIS_RUN
    if _DRINK_EXHAUSTED_THIS_RUN:
        logger.info("本轮脚本已确认喝酒次数耗尽，跳过喝酒恢复")
        return False
    before = read_strength_status()
    emit_run_status("正在恢复疲劳", "正在尝试喝酒恢复疲劳")
    remaining = _drink_remaining_before_entry()
    if remaining == 0:
        return False
    if not _tap_drink_entry():
        return False

    try:
        time.sleep(1.2)
        drank_count = 0
        max_attempts = remaining if remaining is not None and remaining > 0 else MAX_DRINK_ATTEMPTS
        max_attempts = max(1, min(MAX_DRINK_ATTEMPTS, max_attempts))
        for attempt in range(1, max_attempts + 1):
            texts = _current_clean_texts()
            if _dismiss_drink_cost_confirm(texts):
                return drank_count > 0
            if _has_any_clean_text(DRINK_UNAVAILABLE_TEXTS, texts):
                logger.info("喝酒次数或城市条件不可用，跳过喝酒")
                if drank_count <= 0:
                    _mark_drink_exhausted("页面提示喝酒次数不可用")
                return drank_count > 0

            if _has_any_clean_text(DRINK_REPEAT_TEXTS, texts):
                if not _tap_drink_repeat_button():
                    logger.info("未能点击再喝一杯，结束喝酒流程")
                    break
                time.sleep(1.0)
                time.sleep(0.8)
                texts = _current_clean_texts()
                if not _is_drink_select_page(texts) and not _is_rest_area_page(texts) and not _is_strength_page_from_texts(texts):
                    if _finish_drink_animation_and_result():
                        drank_count += 1
                        logger.info(f"已完成第 {drank_count} 次喝酒流程")
                    else:
                        break
                continue

            if _is_drink_select_page(texts):
                if not _tap_drink_choice():
                    logger.warning("未能选择银枝气泡水，结束喝酒流程")
                    break

                if _finish_drink_animation_and_result():
                    drank_count += 1
                    logger.info(f"已完成第 {drank_count} 次喝酒流程")
                    time.sleep(0.8)
                    continue
                break

            if _is_rest_area_page(texts):
                if not _tap_rest_area_drink_button():
                    logger.info("未能进入喝酒选择页，结束喝酒流程")
                    break
                time.sleep(1.0)
                continue

            if _is_strength_page_from_texts(texts):
                if not _tap_drink_entry():
                    break
                time.sleep(1.0)
                continue

            if not _is_drink_select_page(texts):
                if _tap_popup_action(
                    ("确定", "确认"),
                    cropped_pos1=(620, 380),
                    cropped_pos2=(1260, 690),
                    exact=False,
                ):
                    time.sleep(0.8)
                    continue
                if _dismiss_drink_cost_confirm():
                    return drank_count > 0
                logger.debug(f"喝酒第 {attempt} 次未处于可处理页面，继续等待")
                time.sleep(0.8)
                continue

        if drank_count <= 0:
            logger.warning("未找到喝一杯按钮，跳过喝酒")
            return False
        if remaining is not None:
            _DRINK_REMAINING_THIS_RUN = max(0, remaining - drank_count)
            if _DRINK_REMAINING_THIS_RUN == 0:
                _mark_drink_exhausted("本次已喝完叹号提示的剩余次数")

        if _is_rest_area_page() and not _is_drink_select_page() and not _leave_rest_area_page():
            logger.warning("喝酒后未能离开休息区")
            return True

        after = wait_strength_status(timeout=3.0)
        if after is None and not _is_strength_page() and not open_strength_page():
            logger.warning("喝酒后未能回到疲劳页面确认结果")
            return True
        if after is None:
            after = wait_strength_status(timeout=3.0)
        if before and after and after.current < before.current:
            logger.info(f"已喝酒恢复疲劳: {before.current}->{after.current}，共喝酒 {drank_count} 次")
            return True
        if before is None and after:
            logger.info(f"已尝试喝酒恢复疲劳，共喝酒 {drank_count} 次")
            return True
        logger.warning("未确认喝酒恢复成功，但已完成喝酒点击流程")
        return True
    finally:
        if _is_rest_area_page() and not _leave_rest_area_page():
            logger.warning("喝酒流程结束后未能离开休息区")


def drink_on_arrival_if_worthwhile(city_name: str | None) -> bool:
    if not bool(cfg.RunAllowDrink.value):
        return False
    if _DRINK_EXHAUSTED_THIS_RUN:
        logger.info("本轮脚本已确认喝酒次数耗尽，跳过到站喝酒检查")
        return False
    if not is_drink_supported_city(city_name):
        logger.debug(f"{city_name or '当前城市'} 不在喝酒支持主城列表中，跳过主动喝酒")
        return False
    if not open_strength_page():
        logger.warning("主动喝酒时未能打开疲劳页面")
        return False
    try:
        if not should_use_drink_now():
            logger.info("当前疲劳未达到主动喝酒阈值，关闭疲劳页并继续跑商")
            return False
        return use_drink_if_available()
    finally:
        if not close_strength_page():
            logger.warning("主动喝酒结束后未能返回原页面")


def read_strength_status_for_check(required_to_keep_open: int | None = None) -> StrengthStatus | None:
    header_status = wait_trade_header_strength_status(timeout=1.2)
    if header_status is not None:
        logger.info(
            f"交易页顶部疲劳值: {header_status.current}/{header_status.total}，剩余 {header_status.remaining}"
        )
        return header_status

    texts = _current_clean_texts()
    if _page_may_show_strength_status(texts):
        status = wait_strength_status(timeout=1.2)
        if status is not None:
            logger.info(
                f"当前可见疲劳值: {status.current}/{status.total}，剩余 {status.remaining}"
            )
            return status
    if not open_strength_page():
        return None
    status: StrengthStatus | None = None
    keep_open = False
    try:
        status = wait_strength_status(timeout=3.0)
        if required_to_keep_open is not None and status is not None:
            keep_open = status.remaining < max(0, int(required_to_keep_open or 0))
        if status is not None:
            logger.info(
                f"疲劳页读取结果: {status.current}/{status.total}，剩余 {status.remaining}，"
                f"需求 {required_to_keep_open if required_to_keep_open is not None else '-'}，"
                f"{'保留疲劳页用于恢复' if keep_open else '读取后关闭疲劳页'}"
            )
        return status
    finally:
        if not keep_open and not close_strength_page():
            logger.warning("疲劳读取结束后未能返回原页面")


def _ensure_strength_page_for_recovery(action: str) -> bool:
    if _is_strength_page():
        return True
    if open_strength_page():
        return True
    logger.warning(f"{action}前未能打开疲劳页，跳过本次恢复动作")
    return False


def _strength_satisfied_after_recovery(required_fatigue: int, source: str) -> bool:
    required = max(0, int(required_fatigue or 0))
    status = read_strength_status()
    if status is not None:
        logger.info(
            f"{source}后当前疲劳: {status.current}/{status.total}，剩余 {status.remaining}，需求 {required}"
        )
        if status.remaining >= required:
            return True

    if not _is_strength_page() and not open_strength_page():
        logger.warning(f"{source}后未能重新打开疲劳页，无法继续恢复疲劳")
        return False

    status = wait_strength_status(timeout=2.5)
    if status is None:
        logger.warning(f"{source}后已回到疲劳页，但仍未识别到疲劳值")
        return False

    logger.info(
        f"{source}后疲劳页复查: {status.current}/{status.total}，剩余 {status.remaining}，需求 {required}"
    )
    return status.remaining >= required


def recover_strength_by_config(required_fatigue: int = MIN_TRADE_STRENGTH) -> bool:
    if not has_configured_strength_recovery():
        logger.info("未启用任何疲劳恢复资源，停止跑商")
        return False
    if not _is_strength_page() and not _is_bento_page() and not open_strength_page():
        logger.error("未找到体力页面")
        return False

    try:
        if _is_bento_page() and not _leave_bento_page():
            logger.error("未能从便当柜返回体力页面")
            return False

        used_any = False
        for attempt in range(1, MAX_USE_ALL_ATTEMPTS + 1):
            if _visible_strength_enough(required_fatigue):
                return True

            used_this_round = False
            if (
                bool(cfg.RunAllowDrink.value)
                and not _DRINK_EXHAUSTED_THIS_RUN
                and _ensure_strength_page_for_recovery("喝酒恢复")
                and use_drink_if_available()
            ):
                used_any = used_this_round = True
                if _strength_satisfied_after_recovery(required_fatigue, "喝酒恢复"):
                    return True
                if not _is_strength_page():
                    return False

            if (
                not _visible_strength_enough(required_fatigue)
                and bool(cfg.RunAllowFood.value)
                and not _FOOD_UNAVAILABLE_THIS_RUN
            ):
                emit_run_status("正在恢复疲劳", "正在尝试使用便当恢复疲劳")
                if use_food():
                    logger.info("已使用便当恢复疲劳")
                    used_any = used_this_round = True
                    if _strength_satisfied_after_recovery(required_fatigue, "使用便当"):
                        return True
                    if not _is_strength_page():
                        return False

            if not _visible_strength_enough(required_fatigue) and bool(cfg.RunUseStrengthMedicine.value):
                if not _ensure_strength_page_for_recovery("使用体力药"):
                    return False
                if _visible_strength_enough(required_fatigue):
                    return True
                for resource in MEDICINE_RESOURCES:
                    if use_named_strength_resource(resource):
                        used_any = used_this_round = True
                        if _strength_satisfied_after_recovery(required_fatigue, f"使用{resource.name}"):
                            return True
                        if not _is_strength_page():
                            return False
                        break

            if (
                not _visible_strength_enough(required_fatigue)
                and bool(cfg.RunUseHuashi.value)
                and not _HUASHI_EXHAUSTED_THIS_RUN
                and _ensure_strength_page_for_recovery("使用桦石")
                and use_huashi()
            ):
                used_any = used_this_round = True
                if _strength_satisfied_after_recovery(required_fatigue, "使用桦石"):
                    return True
                if not _is_strength_page():
                    return False

            if not used_this_round:
                logger.info(f"第 {attempt} 轮疲劳恢复未找到可用资源")
                break

        logger.error("已按疲劳配置尝试恢复，但没有成功恢复疲劳")
        return used_any and _visible_strength_enough(required_fatigue)
    finally:
        if not close_strength_page():
            logger.warning("疲劳恢复结束后未能返回原页面")


def ensure_strength_available(
    required_fatigue: int = MIN_TRADE_STRENGTH,
    *,
    context: str = "当前操作",
    route: str = "",
    status_fields: dict[str, Any] | None = None,
) -> bool:
    required = max(0, int(required_fatigue or 0))
    status = read_strength_status_for_check(required_to_keep_open=required)
    if status is not None and status.remaining >= required:
        return True
    if status is None:
        logger.warning("未能读取当前疲劳值，跳过主动疲劳恢复判断")
        return True

    fields = status_fields or {}
    remaining_text = str(status.remaining)
    emit_run_status(
        "体力不足",
        f"{context}预计需要 {required} 疲劳，当前剩余 {remaining_text}，正在按疲劳设置恢复",
        route=route,
        **fields,
    )
    if not has_configured_strength_recovery():
        if not close_strength_page():
            logger.warning("疲劳不足且无恢复资源时未能返回原页面")
        emit_run_status(
            "体力不足",
            "未启用可用的疲劳恢复资源，跑商已停止",
            route=route,
            **fields,
        )
        return False

    if recover_strength_by_config(required):
        emit_run_status(
            "疲劳已恢复",
            f"{context}所需疲劳已满足",
            route=route,
            **fields,
        )
        return True

    emit_run_status(
        "体力不足",
        "已按疲劳配置尝试恢复，但没有成功恢复疲劳，跑商已停止",
        route=route,
        **fields,
    )
    return False


def use_strength():
    return recover_strength_by_config()
