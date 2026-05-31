"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-04-04 17:54:58
LastEditTime: 2025-02-11 19:29:24
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

import re
import time
from typing import List, Tuple

import cv2 as cv
import numpy as np
from loguru import logger

import core.control.control as control_state
from app.common.config import cfg
from app.common.runtime_status import emit_run_status
from auto.module.strength import recover_strength_by_config
from auto.run_business.config_updates import (
    TradeRouteReplanRequired,
    disable_trade_product_for_city,
    enable_trade_product_for_city,
    set_trade_product_unlock_state,
)
from core.control.control import input_swipe, input_tap, screenshot, screenshot_image
from core.exception.exception_handling import get_excption
from core.image.image import Image
from core.module.bgr import BGR
from core.module.hsv import HSV
from core.preset import click, find_text, go_home
from core.preset.page_state import PageKind, capture_page_state, classify_page, recover_trade_page
from core.utils.runtime_state import capture_state, has_any_text, ocr_texts
from core.utils.utils import RESOURCES_PATH, read_json

BUY_GOOD_CLICK_X = 807
BUY_GOOD_SAFE_CLICK_X = 835
BUY_GOOD_CLICK_Y_OFFSET = 62
BUY_GOOD_CLICK_Y_MAX = 620
GOOD_SAFE_Y_MAX = 585
BUY_REPORT_TEXTS = ("买入结算报告", "触碰空白区域退出")
BUY_CART_TEXTS = ("全部取消",)
BUY_EMPTY_TEXTS = ("全部买入",)
BUY_CLICK_BLOCKED_TEXTS = ("货币不足", "库存不足", "无法购买", "已售罄")
HAGGLE_PERCENT_LIMIT = 20
HAGGLE_PERCENT_CROP_POS1 = (988, 450)
HAGGLE_PERCENT_CROP_POS2 = (1042, 475)
BUY_CART_GOODS_CROP_POS1 = (860, 145)
BUY_CART_GOODS_CROP_POS2 = (1260, 615)
BUY_CART_SCROLL_DOWN_START = (1060, 565)
BUY_CART_SCROLL_DOWN_END = (1060, 250)
BUY_CART_SCROLL_UP_START = (1060, 250)
BUY_CART_SCROLL_UP_END = (1060, 565)
GOOD_DETAIL_TEXTS = ("获取途径", "拥有数量")
GOOD_LOCKED_TEXTS = ("需要解锁", "未解锁", "本城声望达到", "声望达到", "投资方案")
BUY_CLICK_HINT_CROP1 = (420, 285)
BUY_CLICK_HINT_CROP2 = (860, 430)
BUY_CONFIRM_ATTEMPTS = 5
GOOD_LIST_SCROLL_DOWN_START = (690, 560)
GOOD_LIST_SCROLL_DOWN_END = (690, 210)
GOOD_LIST_SCROLL_UP_START = (690, 210)
GOOD_LIST_SCROLL_UP_END = (690, 560)
GOOD_LIST_SCROLL_TIME = 600
GOOD_LIST_SCROLL_SETTLE_SECONDS = 0.55
GOOD_LIST_STUCK_LIMIT = 2
BOOK_USE_TIMEOUT = 10.0
BOOK_COUNT_MAX_PER_USE = 10
BOOK_POPUP_CROP_POS1 = (300, 150)
BOOK_POPUP_CROP_POS2 = (1020, 590)
BOOK_POPUP_STRONG_TEXTS = ("是否使用", "增加交易品库存")
BOOK_POPUP_SECONDARY_TEXTS = ("确认", "取消", "最多", "最少")
BOOK_NAME_TEXTS = ("进货采购书", "进货采买书", "进货书", "采购书", "采买书")
BOOK_TOOL_BUTTON_TEXTS = ("使用道具",)
BOOK_TOOL_BUTTON_CROP_POS1 = (980, 70)
BOOK_TOOL_BUTTON_CROP_POS2 = (1160, 135)
BOOK_TOOL_BUTTON_FALLBACK_POINT = (1082, 104)
BOOK_MENU_TEXTS = ("使用进货书", "使用进货采购书", "进货采购书", "进货采买书", "进货书", "采购书", "采买书")
BOOK_MENU_CROP_POS1 = (880, 90)
BOOK_MENU_CROP_POS2 = (1210, 360)
BOOK_MENU_FALLBACK_POINTS = ((1082, 162), (1082, 206), (1050, 162))
BOOK_MENU_PANEL_CROP_POS1 = (560, 60)
BOOK_MENU_PANEL_CROP_POS2 = (1040, 720)
BOOK_MENU_USE_BUTTON_X = 922
BOOK_INCREMENT_POINT = (827, 387)
BOOK_CONFIRM_POINT = (966, 537)
BUY_ALL_TEXTS = ("全部买入",)
GOOD_DETAIL_CLOSE_POINTS = ((100, 100), (640, 100), (1200, 620))
FATIGUE_BLOCKED_BGR = [62, 63, 63]
BUY_GOOD_NAME_CROP_POS1 = (622, 136)
BUY_GOOD_NAME_CROP_POS2 = (854, 685)
PRODUCT_SCAN_STEPS = 14
PRODUCT_SCAN_TOP_SCROLL_STEPS = 6
PRODUCT_SCAN_SETTLE_SECONDS = 0.7
PRODUCT_SCAN_FIND_TIMEOUT = 4.0
_COLUMBA_TRADE_DATA = read_json(RESOURCES_PATH / "goods" / "ColumbaTradeData2026.json")
_COLUMBA_LOCAL_MARKET_DATA = read_json(RESOURCES_PATH / "goods" / "ColumbaLocalMarketData2026.json")


def _raise_replan_required(city_name: str | None, good: str, reason: str):
    city = str(city_name or "").strip()
    key = f"{city}/{good}" if city else good
    raise TradeRouteReplanRequired(f"{key} {reason}，已更新配置，需要重新规划路线")


def known_buy_goods_for_city(city_name: str | None) -> list[str]:
    city = str(city_name or "").strip()
    if not city:
        return []
    products = _COLUMBA_TRADE_DATA.get("products", []) if isinstance(_COLUMBA_TRADE_DATA, dict) else []
    goods: list[str] = []
    for product in products:
        if not isinstance(product, dict):
            continue
        name = str(product.get("name") or "").strip()
        if not name:
            continue
        if (product.get("buyPrices") or {}).get(city):
            goods.append(name)
    return goods


def city_trade_goods_order_by_base_price(city_name: str | None) -> list[str]:
    city = str(city_name or "").strip()
    if not city or not isinstance(_COLUMBA_LOCAL_MARKET_DATA, dict):
        return []

    buy_goods = _COLUMBA_LOCAL_MARKET_DATA.get("buy_goods", {})
    city_goods = buy_goods.get(city, {}) if isinstance(buy_goods, dict) else {}
    if not isinstance(city_goods, dict):
        return []

    ranked: list[tuple[int, int, str]] = []
    for index, (name, info) in enumerate(city_goods.items()):
        if not isinstance(info, dict):
            continue
        base_price = int(info.get("base_price") or 0)
        if base_price <= 0:
            continue
        ranked.append((-base_price, index, str(name)))
    ranked.sort()
    return [name for _, _, name in ranked]


def _configured_city_status(city_name: str | None) -> dict[str, bool]:
    city = str(city_name or "").strip()
    if not city:
        return {}
    status_by_city = dict(cfg.tradePlannerProductUnlockStatusByCity.value or {})
    result = dict(status_by_city.get(city) or {})
    flat_status = dict(cfg.tradePlannerProductUnlockStatus.value or {})
    prefix = f"{city}/"
    for key, value in flat_status.items():
        text = str(key)
        if text.startswith(prefix):
            result[text[len(prefix):]] = bool(value)
    return result


def _scan_targets_for_city(city_name: str | None) -> tuple[list[str], bool]:
    known_goods = known_buy_goods_for_city(city_name)
    if not known_goods:
        return [], False
    status = _configured_city_status(city_name)
    if any(good not in status for good in known_goods):
        return known_goods, True
    locked_goods = [good for good in known_goods if status.get(good) is False]
    return locked_goods, False


def _normalize_good_text(text: str) -> str:
    return str(text or "").replace(" ", "").strip()


def _match_known_good(text: str, goods: list[str]) -> str | None:
    normalized = _normalize_good_text(text)
    if not normalized:
        return None
    for good in goods:
        if good in normalized or normalized in good:
            return good
    return None


def _visible_good_positions(goods: list[str]) -> dict[str, Tuple[int, int]]:
    image = screenshot()
    image.crop_image(BUY_GOOD_NAME_CROP_POS1, BUY_GOOD_NAME_CROP_POS2)
    positions: dict[str, Tuple[int, int]] = {}
    for item in image.ocr():
        good = _match_known_good(item.get("text", ""), goods)
        if not good or good in positions:
            continue
        position = item["position"]
        center_x = int((position[0][0] + position[2][0]) / 2)
        center_y = int((position[0][1] + position[2][1]) / 2)
        positions[good] = (center_x, center_y)
    return positions


def _visible_city_trade_entries(city_name: str | None) -> list[tuple[int, str, Tuple[int, int]]]:
    order = city_trade_goods_order_by_base_price(city_name)
    if not order:
        return []
    positions = _visible_good_positions(order)
    entries = [(order.index(good), good, pos) for good, pos in positions.items() if good in order]
    entries.sort(key=lambda item: item[0])
    return entries


def _visible_trade_signature(entries: list[tuple[int, str, Tuple[int, int]]]) -> tuple[str, ...]:
    return tuple(good for _, good, _ in entries)


def _scroll_trade_goods(direction: str):
    if direction == "down":
        input_swipe(GOOD_LIST_SCROLL_DOWN_START, GOOD_LIST_SCROLL_DOWN_END, swipe_time=GOOD_LIST_SCROLL_TIME)
    elif direction == "up":
        input_swipe(GOOD_LIST_SCROLL_UP_START, GOOD_LIST_SCROLL_UP_END, swipe_time=GOOD_LIST_SCROLL_TIME)
    else:
        raise ValueError(f"unsupported trade goods scroll direction: {direction}")
    time.sleep(GOOD_LIST_SCROLL_SETTLE_SECONDS)


def _scroll_trade_goods_to_top(city_name: str | None, max_steps: int = PRODUCT_SCAN_TOP_SCROLL_STEPS) -> bool:
    last_signature: tuple[str, ...] | None = None
    for step in range(max_steps):
        entries = _visible_city_trade_entries(city_name)
        if entries:
            indexes = [index for index, _, _ in entries]
            visible_text = "->".join(good for _, good, _ in entries)
            if min(indexes) <= 0:
                logger.info(f"交易所商品扫描已位于顶部: city={city_name} visible={visible_text}")
                return True
            signature = _visible_trade_signature(entries)
            if signature == last_signature:
                logger.info(
                    "交易所商品扫描向上滑动后可见商品未变化，按当前视口开始向下扫描: "
                    f"city={city_name} visible={visible_text}"
                )
                return False
            last_signature = signature
            logger.info(
                "交易所商品扫描先回到列表顶部: "
                f"city={city_name} step={step + 1} visible={visible_text}"
            )
        else:
            logger.debug(f"交易所商品扫描回顶部时未识别到可见商品: city={city_name} step={step + 1}")
        _scroll_trade_goods("up")
    return False


def _direction_to_target_index(
    target_index: int,
    entries: list[tuple[int, str, Tuple[int, int]]],
    order_len: int,
) -> str | None:
    indexes = [index for index, _, _ in entries]
    if not indexes:
        return None
    min_index = min(indexes)
    max_index = max(indexes)
    if target_index < min_index:
        if min_index <= 0:
            return None
        return "up"
    if target_index > max_index:
        if max_index >= order_len - 1:
            return None
        return "down"
    return None


def find_good_by_known_city_order(
    good: str,
    buy_city_name: str | None,
    timeout: float = 8.0,
) -> tuple[Tuple[int, int] | None, object | None, bool]:
    order = city_trade_goods_order_by_base_price(buy_city_name)
    if not order or good not in order:
        return None, None, False

    target_index = order.index(good)
    start = time.perf_counter()
    last_signature: tuple[str, ...] | None = None
    last_direction: str | None = None
    stuck_count = 0

    while time.perf_counter() - start < timeout:
        close_good_detail_popup()
        pos, image = find_text(
            good,
            cropped_pos1=BUY_GOOD_NAME_CROP_POS1,
            cropped_pos2=BUY_GOOD_NAME_CROP_POS2,
            log=False,
        )
        if pos:
            return pos, image, True

        entries = _visible_city_trade_entries(buy_city_name)
        for index, entry_good, entry_pos in entries:
            if entry_good == good:
                logger.info(f"按已知排序定位到商品: {good} index={index} pos={entry_pos}")
                return entry_pos, screenshot(), True

        if not entries:
            logger.debug("未识别到当前可见交易品，退回普通商品查找")
            return None, None, False

        direction = _direction_to_target_index(target_index, entries, len(order))
        visible_text = "->".join(good_name for _, good_name, _ in entries)
        if not direction:
            logger.warning(
                "目标商品应在当前可见区或已经到达列表边界，停止继续拖动: "
                f"city={buy_city_name} target={good} target_index={target_index} visible={visible_text}"
            )
            return None, None, True

        signature = _visible_trade_signature(entries)
        if signature == last_signature and direction == last_direction:
            stuck_count += 1
        else:
            stuck_count = 0
        if stuck_count >= GOOD_LIST_STUCK_LIMIT:
            logger.warning(
                "交易品列表滑动后可见商品未变化，判断已到边界或卡住，停止继续拖动: "
                f"city={buy_city_name} target={good} direction={direction} visible={visible_text}"
            )
            return None, None, True

        logger.info(
            "按已知交易品顺序滑动列表: "
            f"city={buy_city_name} target={good} target_index={target_index} "
            f"direction={direction} visible={visible_text}"
        )
        last_signature = signature
        last_direction = direction
        _scroll_trade_goods(direction)

    return None, None, True


def _scan_city_product_unlocks(
    city_name: str | None,
    targets: list[str],
) -> tuple[list[str], list[str]]:
    order = city_trade_goods_order_by_base_price(city_name)
    if order and all(target in order for target in targets):
        return _scan_city_product_unlocks_by_known_order(city_name, targets, order)

    remaining = set(targets)
    locked: list[str] = []
    unlocked: list[str] = []
    for step in range(PRODUCT_SCAN_STEPS):
        close_good_detail_popup()
        visible = _visible_good_positions(sorted(remaining))
        for good, pos in visible.items():
            if good not in remaining:
                continue
            is_locked = is_good_locked(good, pos, capture=False)
            if is_locked:
                locked.append(good)
            else:
                unlocked.append(good)
            remaining.discard(good)
        if not remaining:
            break
        if step < PRODUCT_SCAN_STEPS // 2:
            input_swipe((690, 560), (690, 210), swipe_time=650)
        else:
            input_swipe((690, 210), (690, 560), swipe_time=650)
        time.sleep(PRODUCT_SCAN_SETTLE_SECONDS)
    return locked, unlocked


def _scan_city_product_unlocks_by_known_order(
    city_name: str | None,
    targets: list[str],
    order: list[str],
) -> tuple[list[str], list[str]]:
    remaining = set(targets)
    locked: list[str] = []
    unlocked: list[str] = []
    _scroll_trade_goods_to_top(city_name)

    last_signature: tuple[str, ...] | None = None
    stuck_count = 0

    for step in range(PRODUCT_SCAN_STEPS):
        close_good_detail_popup()
        entries = _visible_city_trade_entries(city_name)
        if not entries:
            logger.debug(f"交易所商品顺序扫描未识别到可见商品，执行一次向下滑动: city={city_name} step={step}")
            _scroll_trade_goods("down")
            continue

        for _, good, pos in entries:
            if good not in remaining:
                continue
            if is_good_locked(good, pos, capture=False):
                locked.append(good)
            else:
                unlocked.append(good)
            remaining.discard(good)
        if not remaining:
            break

        indexes = [index for index, _, _ in entries]
        max_index = max(indexes)
        if max_index >= len(order) - 1:
            logger.warning(
                "交易所商品顺序扫描已到底部，仍有未找到商品: "
                f"city={city_name} remaining={sorted(remaining)}"
            )
            break

        signature = _visible_trade_signature(entries)
        if signature == last_signature:
            stuck_count += 1
        else:
            stuck_count = 0
        if stuck_count >= GOOD_LIST_STUCK_LIMIT:
            logger.warning(
                "交易所商品顺序扫描向下滑动后可见商品未变化，判断已到底部或卡住，停止继续拖动: "
                f"city={city_name} remaining={sorted(remaining)}"
            )
            break

        visible_text = "->".join(good for _, good, _ in entries)
        logger.info(
            "按已知交易品顺序从上到下扫描商品解锁: "
            f"city={city_name} remaining={sorted(remaining)} visible={visible_text}"
        )
        last_signature = signature
        _scroll_trade_goods("down")

    return locked, unlocked


def analyze_city_trade_products(city_name: str | None) -> bool:
    """Scan the buy page for city product unlock status.

    The first visit to a city scans all known buy goods. Later visits only
    re-check goods previously recorded as locked. Returns whether the route
    should be replanned.
    """
    targets, full_scan = _scan_targets_for_city(city_name)
    if not targets:
        return False

    city = str(city_name or "").strip()
    emit_run_status(
        "正在分析交易所商品",
        f"{city} 首次扫描全部商品" if full_scan else f"{city} 复查未解锁商品",
        current_city=city,
        goods=targets,
    )
    logger.info(
        f"开始分析交易所商品解锁状态: city={city} "
        f"full_scan={full_scan} targets={targets}"
    )
    locked, unlocked = _scan_city_product_unlocks(city, targets)
    replan_needed = False
    for good in locked:
        _, need_replan = set_trade_product_unlock_state(
            city,
            good,
            False,
            reason="交易所商品扫描",
        )
        replan_needed = replan_needed or need_replan
    for good in unlocked:
        _, need_replan = set_trade_product_unlock_state(
            city,
            good,
            True,
            reason="交易所商品扫描",
        )
        replan_needed = replan_needed or need_replan
    missing = sorted(set(targets) - set(locked) - set(unlocked))
    if full_scan:
        for good in missing:
            _, need_replan = set_trade_product_unlock_state(
                city,
                good,
                False,
                reason="交易所商品全量扫描未找到",
            )
            replan_needed = replan_needed or need_replan
    logger.info(
        f"交易所商品扫描完成: city={city} unlocked={unlocked} "
        f"locked={locked} missing={missing}"
    )
    if missing:
        capture_state(
            "buy_product_scan_missing",
            extra={"city": city, "missing": missing, "full_scan": full_scan},
        )
        capture_page_state(
            "buy_product_scan_missing",
            extra={"city": city, "missing": missing, "full_scan": full_scan},
        )
    return replan_needed


def ensure_buy_page(label: str = "buy_not_on_page") -> bool:
    close_good_detail_popup()
    state = classify_page()
    if state.kind == PageKind.BUY_PAGE:
        return True
    recovery = recover_trade_page("buy", label=label)
    if recovery.recovered:
        return True
    state = recovery.after
    capture_page_state(
        label,
        extra={
            "expected": PageKind.BUY_PAGE.value,
            "actual": state.kind.value,
            "confidence": state.confidence,
            "suggested_action": state.suggested_action,
        },
    )
    return False


def recover_buy_strength(context: str, label: str) -> bool:
    logger.info("疲劳不足")
    capture_state(label)
    capture_page_state(label)
    emit_run_status("体力不足", f"{context}疲劳不足，正在按疲劳设置恢复")
    if not recover_strength_by_config():
        emit_run_status("体力不足", "疲劳恢复失败，跑商已停止")
        return False
    if not ensure_buy_page(f"{label}_after_recovery"):
        emit_run_status("恢复失败", "恢复疲劳后未能回到买入页面")
        return False
    return True


def close_buy_report():
    for attempt in range(1, 4):
        image = screenshot()
        texts = ocr_texts(image)
        state = classify_page(image)
        if state.kind in (PageKind.BUSINESS_MENU, PageKind.BUY_PAGE, PageKind.SELL_PAGE):
            return True
        if state.kind != PageKind.BUY_REPORT and not has_any_text(texts, BUY_REPORT_TEXTS):
            return True
        input_tap((100, 100))
        time.sleep(0.8)

    image = screenshot()
    texts = ocr_texts(image)
    state = classify_page(image)
    if state.kind in (PageKind.BUSINESS_MENU, PageKind.BUY_PAGE, PageKind.SELL_PAGE):
        return True
    if state.kind != PageKind.BUY_REPORT and not has_any_text(texts, BUY_REPORT_TEXTS):
        return True

    capture_state("buy_report_close_failed", image, extra={"attempts": attempt, "state": state.kind.value})
    capture_page_state("buy_report_close_failed", image, extra={"attempts": attempt, "state": state.kind.value})
    return False


def is_good_detail_popup(image=None) -> bool:
    texts = ocr_texts(image)
    return has_any_text(texts, GOOD_DETAIL_TEXTS)


def close_good_detail_popup(image=None) -> bool:
    if not is_good_detail_popup(image):
        return False
    for point in GOOD_DETAIL_CLOSE_POINTS:
        input_tap(point)
        time.sleep(0.6)
        if not is_good_detail_popup():
            return True
    capture_state("buy_good_detail_close_failed", extra={"texts": ocr_texts()[:20]})
    capture_page_state("buy_good_detail_close_failed", extra={"texts": ocr_texts()[:20]})
    return False


def buy_business(
    primary_goods: List[str],
    secondary_goods: List[str],
    num: int = 0,
    max_book: int = 0,
    buy_city_name: str | None = None,
):
    """
    购买商品

    :param primary_goods: 主要商品列表
    :param secondary_goods: 次要商品列表
    :param num: 目标议价幅度百分比
    :param max_book: 最大使用进货书量
    """
    if not ensure_buy_page("buy_business_start_not_on_page"):
        return False

    goods_order = list(dict.fromkeys([*primary_goods, *secondary_goods]))
    book = use_planned_books(goods_order, max_book, buy_city_name)
    if book < 0:
        return False

    failed_goods: set[str] = set()
    if try_select_all_buy_when_ordered(goods_order, buy_city_name):
        done = True
    else:
        done, book = try_select_all_buy_then_reorder_tail(
            goods_order,
            buy_city_name,
            book,
            max_book,
        )

    def process_goods(book, good):
        if good in failed_goods:
            return book
        close_good_detail_popup()
        emit_run_status(
            "正在购买商品",
            f"正在尝试购买 {good}",
            current_city=buy_city_name or "",
            goods=[good],
        )
        if (boatload := get_boatload()) == 0:
            logger.info("已满载")
            emit_run_status(
                "货舱已满",
                "当前货舱已满，准备结算买入",
                current_city=buy_city_name or "",
            )
            return True
        result, book = buy_good(good, book, max_book, buy_city_name=buy_city_name)
        if result is None:
            logger.info(f"进货书已用完")
        elif not result:
            logger.info(f"商品{good}购买失败")
            failed_goods.add(good)
        logger.info(f"剩余载货量: {boatload}%")
        return book

    if not done:
        for good in primary_goods:
            if (book := process_goods(book, good)) is True:
                done = True
                break
        for good in secondary_goods:
            if done:
                break
            if (book := process_goods(book, good)) is True:
                break
    if not is_empty_goods():
        if num > 0:
            emit_run_status("正在议价", f"目标议价幅度：{min(int(num), HAGGLE_PERCENT_LIMIT)}%", current_city=buy_city_name or "")
            if not click_bargain_button(num):
                capture_state("buy_bargain_failed", extra={"num": num})
                capture_page_state("buy_bargain_failed", extra={"num": num})
                return False
        emit_run_status("正在确认买入", "正在提交购买结算", current_city=buy_city_name or "")
        if not click_buy_button():
            capture_state("buy_confirm_failed")
            capture_page_state("buy_confirm_failed")
            return False
        time.sleep(0.5)
        if not close_buy_report():
            return False
        return True
    else:
        logger.error("未购买物品")
        capture_state("buy_no_goods_selected")
        capture_page_state("buy_no_goods_selected")
        go_home()
        return False


def is_empty_goods():
    if close_good_detail_popup():
        time.sleep(0.3)
    texts = ocr_texts(cropped_pos1=(860, 80), cropped_pos2=(1260, 170))
    if not texts:
        texts = ocr_texts()
    if has_any_text(texts, BUY_CART_TEXTS):
        return False
    if has_any_text(texts, BUY_EMPTY_TEXTS):
        return True

    capture_state("buy_cart_state_unknown", extra={"texts": texts[:20]})
    capture_page_state("buy_cart_state_unknown", extra={"texts": texts[:20]})
    return True


def get_buy_click_blocker(image=None) -> str | None:
    texts = ocr_texts(
        image,
        cropped_pos1=BUY_CLICK_HINT_CROP1,
        cropped_pos2=BUY_CLICK_HINT_CROP2,
    )
    for text in texts:
        for blocked_text in BUY_CLICK_BLOCKED_TEXTS:
            if blocked_text in text:
                return blocked_text
    return None


def buy_good_click_points(pos: Tuple[int, int]) -> list[Tuple[int, int]]:
    lower_row_y = pos[1] + BUY_GOOD_CLICK_Y_OFFSET
    candidates = [
        (BUY_GOOD_SAFE_CLICK_X, lower_row_y),
        (BUY_GOOD_CLICK_X, lower_row_y),
        (865, lower_row_y),
    ]
    points: list[Tuple[int, int]] = []
    for point in candidates:
        if point in points:
            continue
        if point[1] > BUY_GOOD_CLICK_Y_MAX:
            continue
        points.append(point)
    return points


def is_good_locked(good: str, pos: Tuple[int, int], *, capture: bool = True) -> bool:
    row_top = max(120, pos[1] - 55)
    row_bottom = min(690, pos[1] + 90)
    texts = ocr_texts(cropped_pos1=(500, row_top), cropped_pos2=(860, row_bottom))
    if has_any_text(texts, GOOD_LOCKED_TEXTS):
        if capture:
            capture_state(
                "buy_good_locked",
                extra={"good": good, "pos": pos, "texts": texts[:20]},
            )
            capture_page_state(
                "buy_good_locked",
                extra={"good": good, "pos": pos, "texts": texts[:20]},
            )
        logger.warning(f"商品{good}未解锁，跳过")
        return True
    return False


def _find_book_target(goods: list[str], buy_city_name: str | None = None) -> tuple[str, Tuple[int, int]] | None:
    for good in goods:
        close_good_detail_popup()
        pos, _ = find_text(
            good,
            cropped_pos1=(622, 136),
            cropped_pos2=(854, 685),
            log=False,
        )
        if not pos:
            pos, _ = find_good(good, buy_city_name=buy_city_name)
        if not pos:
            continue
        if is_good_locked(good, pos):
            disable_trade_product_for_city(
                buy_city_name,
                good,
                reason="使用进货书前识别到未解锁提示",
            )
            _raise_replan_required(buy_city_name, good, "未解锁")
            continue
        return good, pos
    return None


def read_visible_trade_goods_order(candidates: list[str]) -> list[str]:
    image = screenshot()
    image.crop_image(BUY_GOOD_NAME_CROP_POS1, BUY_GOOD_NAME_CROP_POS2)
    matched: list[tuple[int, str]] = []
    for item in image.ocr():
        text = str(item.get("text", "")).replace(" ", "")
        if not text:
            continue
        for good in candidates:
            if good in text or text in good:
                position = item["position"]
                center_y = int((position[0][1] + position[2][1]) / 2)
                matched.append((center_y, good))
                break

    order: list[str] = []
    for _, good in sorted(matched, key=lambda item: item[0]):
        if good not in order:
            order.append(good)
    return order


def _trade_order_target_block(
    goods: list[str],
    buy_city_name: str | None,
) -> tuple[list[str], dict[str, int]] | None:
    goods = list(dict.fromkeys(good for good in goods if good))
    if not goods:
        return None

    fixed_order = city_trade_goods_order_by_base_price(buy_city_name)
    if not fixed_order:
        return None

    positions = {good: index for index, good in enumerate(fixed_order)}
    if any(good not in positions for good in goods):
        logger.debug(
            "部分规划商品缺少基础价排序数据，保持逐个购买: "
            f"city={buy_city_name} planned={'->'.join(goods)}"
        )
        return None

    planned_goods = set(goods)
    target_indexes = sorted(positions[good] for good in goods)
    first_index = target_indexes[0]
    last_index = target_indexes[-1]
    ordered_targets = fixed_order[first_index : last_index + 1]
    if len(ordered_targets) != len(goods) or any(good not in planned_goods for good in ordered_targets):
        logger.debug(
            "规划商品在基础价交易所排序中不连续，保持逐个购买: "
            f"city={buy_city_name} ordered={'->'.join(ordered_targets)} planned={'->'.join(goods)}"
        )
        return None
    return ordered_targets, positions


def goods_follow_city_trade_order(goods: list[str], buy_city_name: str | None) -> bool:
    goods = list(dict.fromkeys(good for good in goods if good))
    if not goods:
        return False

    target_block = _trade_order_target_block(goods, buy_city_name)
    if target_block:
        ordered_targets, _ = target_block
        bottom_good = ordered_targets[-1]
        if goods[-1] != bottom_good:
            logger.debug(
                "规划最后购买商品不是连续目标中最靠下商品，保持逐个购买: "
                f"city={buy_city_name} bottom={bottom_good} planned_last={goods[-1]} "
                f"ordered={'->'.join(ordered_targets)}"
            )
            return False
        logger.info(
            "规划商品按基础价交易所排序连续，且最后购买商品最靠下，使用全部买入: "
            f"city={buy_city_name} ordered={'->'.join(ordered_targets)} planned={'->'.join(goods)}"
        )
        return True

    visible_order = read_visible_trade_goods_order(goods)
    if len(visible_order) < 2:
        return False
    if goods[: len(visible_order)] == visible_order:
        logger.info(f"可见交易品顺序与规划一致: {'->'.join(visible_order)}")
        return True
    logger.debug(
        "可见交易品顺序与规划不一致，保持逐个购买: "
        f"visible={'->'.join(visible_order)} planned={'->'.join(goods[:len(visible_order)])}"
    )
    return False


def _ocr_tap_text(texts: tuple[str, ...], cropped_pos1=(0, 0), cropped_pos2=(0, 0)) -> bool:
    image = screenshot()
    image.crop_image(cropped_pos1, cropped_pos2)
    for item in image.ocr():
        item_text = str(item.get("text", "")).replace(" ", "")
        if not any(text in item_text for text in texts):
            continue
        position = item["position"]
        center_x = int((position[0][0] + position[2][0]) / 2)
        center_y = int((position[0][1] + position[2][1]) / 2)
        input_tap((center_x, center_y))
        return True
    return False


def is_book_popup() -> bool:
    texts = ocr_texts(cropped_pos1=BOOK_POPUP_CROP_POS1, cropped_pos2=BOOK_POPUP_CROP_POS2)
    if has_any_text(texts, BOOK_POPUP_STRONG_TEXTS):
        return True
    return has_any_text(texts, BOOK_NAME_TEXTS) and has_any_text(texts, BOOK_POPUP_SECONDARY_TEXTS)


def wait_book_popup(timeout: float = 3.0) -> bool:
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        if is_book_popup():
            return True
        time.sleep(0.2)
    return False


def tap_book_tool_button() -> bool:
    close_good_detail_popup()
    if _ocr_tap_text(BOOK_TOOL_BUTTON_TEXTS, BOOK_TOOL_BUTTON_CROP_POS1, BOOK_TOOL_BUTTON_CROP_POS2):
        return True
    input_tap(BOOK_TOOL_BUTTON_FALLBACK_POINT)
    return True


def _item_center(item) -> tuple[int, int]:
    position = item["position"]
    return (
        int((position[0][0] + position[2][0]) / 2),
        int((position[0][1] + position[2][1]) / 2),
    )


def tap_book_menu_use_button() -> bool:
    image = screenshot()
    image.crop_image(BOOK_MENU_PANEL_CROP_POS1, BOOK_MENU_PANEL_CROP_POS2)
    items = list(image.ocr())
    target_y: int | None = None
    for item in items:
        text = str(item.get("text", "")).replace(" ", "")
        if not any(target in text for target in BOOK_MENU_TEXTS):
            continue
        _, target_y = _item_center(item)
        break
    if target_y is None:
        return False

    use_candidates: list[tuple[int, int]] = []
    for item in items:
        text = str(item.get("text", "")).replace(" ", "")
        if text != "使用":
            continue
        center_x, center_y = _item_center(item)
        if abs(center_y - target_y) <= 32:
            use_candidates.append((center_x, center_y))
    if use_candidates:
        use_pos = max(use_candidates, key=lambda point: point[0])
    else:
        use_pos = (BOOK_MENU_USE_BUTTON_X, target_y)
    logger.info(f"点击进货书所在行的使用按钮: {use_pos}")
    input_tap(use_pos)
    return True


def tap_book_menu_item() -> bool:
    if tap_book_menu_use_button():
        return True
    for point in BOOK_MENU_FALLBACK_POINTS:
        input_tap(point)
        time.sleep(0.35)
        if is_book_popup():
            return True
    return False


def open_book_popup() -> bool:
    for attempt in range(1, 4):
        if is_book_popup():
            return True
        logger.debug(f"尝试通过使用道具打开进货书弹窗: {attempt}")
        if not tap_book_tool_button():
            continue
        time.sleep(0.4)
        if wait_book_popup(timeout=0.6):
            return True
        if tap_book_menu_item() and wait_book_popup(timeout=1.5):
            return True
        close_good_detail_popup()
    return False


def tap_buy_all() -> bool:
    close_good_detail_popup()
    if _ocr_tap_text(BUY_ALL_TEXTS):
        return True
    if _ocr_tap_text(BUY_ALL_TEXTS, cropped_pos1=(1070, 70), cropped_pos2=(1265, 135)):
        return True
    input_tap((1187, 103))
    return True


def clear_buy_selection() -> bool:
    if is_empty_goods():
        return True
    image = screenshot()
    for item in image.ocr():
        text = str(item.get("text", "")).replace(" ", "")
        if "全部取消" not in text:
            continue
        position = item["position"]
        center_x = int((position[0][0] + position[2][0]) / 2)
        center_y = int((position[0][1] + position[2][1]) / 2)
        input_tap((center_x, center_y))
        time.sleep(0.5)
        return is_empty_goods()
    input_tap((1187, 103))
    time.sleep(0.5)
    if is_empty_goods():
        return True
    capture_state("buy_clear_selection_failed", image)
    capture_page_state("buy_clear_selection_failed", image)
    return False


def find_buy_cart_good(good: str) -> Tuple[int, int] | None:
    image = screenshot()
    image.crop_image(BUY_CART_GOODS_CROP_POS1, BUY_CART_GOODS_CROP_POS2)
    for item in image.ocr():
        text = str(item.get("text", "")).replace(" ", "")
        if good not in text and text not in good:
            continue
        position = item["position"]
        center_x = int((position[0][0] + position[2][0]) / 2)
        center_y = int((position[0][1] + position[2][1]) / 2)
        return center_x, center_y
    return None


def scroll_buy_cart(direction: str):
    if direction == "down":
        input_swipe(BUY_CART_SCROLL_DOWN_START, BUY_CART_SCROLL_DOWN_END, swipe_time=500)
    elif direction == "up":
        input_swipe(BUY_CART_SCROLL_UP_START, BUY_CART_SCROLL_UP_END, swipe_time=500)
    else:
        raise ValueError(f"unsupported buy cart scroll direction: {direction}")
    time.sleep(0.45)


def remove_buy_cart_good(good: str) -> bool:
    directions = [None, "down", "down", "up", "up"]
    for attempt, direction in enumerate(directions, start=1):
        close_good_detail_popup()
        if direction:
            scroll_buy_cart(direction)
        pos = find_buy_cart_good(good)
        if not pos:
            continue
        logger.info(f"从已买列表移出商品: {good} pos={pos}")
        input_tap(pos)
        time.sleep(0.5)
        if not find_buy_cart_good(good):
            return True
        logger.debug(f"第 {attempt} 次移出 {good} 后仍在已买列表，继续尝试")

    capture_state("buy_cart_remove_good_failed", extra={"good": good})
    capture_page_state("buy_cart_remove_good_failed", extra={"good": good})
    return False


def try_select_all_buy_when_ordered(goods: list[str], buy_city_name: str | None) -> bool:
    if not goods_follow_city_trade_order(goods, buy_city_name):
        return False
    emit_run_status(
        "正在购买商品",
        "规划商品顺序与交易所顺序一致，正在全部买入",
        current_city=buy_city_name or "",
        goods=goods,
    )
    for attempt in range(1, 4):
        tap_buy_all()
        time.sleep(0.8)
        if not is_empty_goods():
            logger.info("规划商品顺序匹配交易所顺序，已选择全部买入")
            return True
        logger.debug(f"全部买入第 {attempt} 次未选中商品，继续尝试")
    logger.warning("全部买入后未检测到已选商品，回退为逐个购买")
    return False


def can_reorder_tail_after_buy_all(goods: list[str], buy_city_name: str | None) -> bool:
    goods = list(dict.fromkeys(good for good in goods if good))
    if len(goods) < 2:
        return False
    target_block = _trade_order_target_block(goods, buy_city_name)
    if not target_block:
        return False
    ordered_targets, _ = target_block
    if goods[-1] == ordered_targets[-1]:
        return False
    logger.info(
        "规划商品连续但最后商品不是交易所最下方，尝试全买后重排尾部: "
        f"city={buy_city_name} ordered={'->'.join(ordered_targets)} planned={'->'.join(goods)} "
        f"remove={'->'.join([goods[-1], goods[-2]])} reselect={'->'.join(goods[-2:])}"
    )
    return True


def try_select_all_buy_then_reorder_tail(
    goods: list[str],
    buy_city_name: str | None,
    book: int,
    max_book: int,
) -> tuple[bool, int]:
    goods = list(dict.fromkeys(good for good in goods if good))
    if not can_reorder_tail_after_buy_all(goods, buy_city_name):
        return False, book

    emit_run_status(
        "正在购买商品",
        "正在全部买入并重排最后两个商品",
        current_city=buy_city_name or "",
        goods=goods,
    )
    for attempt in range(1, 4):
        tap_buy_all()
        time.sleep(0.8)
        if not is_empty_goods():
            break
        logger.debug(f"尾部重排快买：全部买入第 {attempt} 次未选中商品，继续尝试")
    else:
        logger.warning("尾部重排快买：全部买入后未检测到已选商品")
        return False, book

    tail_goods = goods[-2:]
    for good in (tail_goods[1], tail_goods[0]):
        if remove_buy_cart_good(good):
            continue
        logger.warning(f"尾部重排快买：无法从已买列表移出 {good}，清空选择后回退逐个购买")
        clear_buy_selection()
        return False, book

    for good in tail_goods:
        result, book = buy_good(good, book, max_book, buy_city_name=buy_city_name)
        if result:
            continue
        logger.warning(f"尾部重排快买：重新选择 {good} 失败，清空选择后回退逐个购买")
        clear_buy_selection()
        return False, book

    logger.info(f"尾部重排快买完成: {'->'.join(tail_goods)}")
    return True, book


def use_planned_books(
    goods: list[str],
    max_book: int,
    buy_city_name: str | None = None,
) -> int:
    max_book = max(0, int(max_book or 0))
    if max_book <= 0:
        return 0
    if not goods:
        return 0

    emit_run_status(
        "正在使用进货书",
        f"本段计划先使用 {max_book} 本进货书",
        current_city=buy_city_name or "",
        goods=goods,
    )
    used = 0
    while used < max_book:
        target = _find_book_target(goods, buy_city_name)
        if not target:
            capture_state(
                "buy_book_target_missing",
                extra={"goods": goods, "used": used, "max_book": max_book},
            )
            capture_page_state(
                "buy_book_target_missing",
                extra={"goods": goods, "used": used, "max_book": max_book},
            )
            return -1
        good, pos = target
        count = min(max_book - used, BOOK_COUNT_MAX_PER_USE)
        emit_run_status(
            "正在使用进货书",
            f"对 {good} 使用 {count} 本进货书（{used + count}/{max_book}）",
            current_city=buy_city_name or "",
            goods=[good],
        )
        if not use_book(pos, used, count=count):
            return -1
        used += count
    return used


def buy_good(
    good: str,
    book: int,
    max_book: int,
    again: bool = False,
    buy_city_name: str | None = None,
):
    logger.info(f"正在购买: {good}")
    close_good_detail_popup()
    pos, image = find_text(
        good,
        cropped_pos1=(622, 136),
        cropped_pos2=(854, 685),
        log=False,
    )  # 点击商品
    if not pos:
        pos, image = find_good(good, buy_city_name=buy_city_name)  # 点击失败查找并点击商品
    if pos and image is not None:
        if pos[1] > GOOD_SAFE_Y_MAX:
            input_swipe((690, 560), (690, 360), swipe_time=500)
            time.sleep(0.8)
            pos, image = find_text(
                good,
                cropped_pos1=(622, 136),
                cropped_pos2=(854, 685),
                log=False,
            )
            if not pos:
                pos, image = find_good(good, buy_city_name=buy_city_name)
        if not pos:
            return False, book
        if is_good_locked(good, pos):
            disable_trade_product_for_city(
                buy_city_name,
                good,
                reason="购买页识别到未解锁提示",
            )
            _raise_replan_required(buy_city_name, good, "未解锁")
            return False, book

        bgr = image.get_bgr((641, pos[1]))
        logger.debug(f"是否进货检测: {bgr}")
        if 13 <= bgr.r <= 16:
            if book < max_book:
                if not use_book(pos, book):
                    return False, book
                result = not again and buy_good(
                    good,
                    book,
                    max_book,
                    again=True,
                    buy_city_name=buy_city_name,
                )[0]
                return result, book + 1  # 如果不是重复运行则使用再次购买，进货书使用次数+1
            else:
                return None, book
        else:
            logger.info(f"点击商品: {good}")
            buy_points = buy_good_click_points(pos)
            for attempt, buy_pos in enumerate(buy_points, start=1):
                input_tap(buy_pos)
                time.sleep(0.35)
                click_image = screenshot()
                if close_good_detail_popup(click_image):
                    capture_state(
                        "buy_good_click_opened_detail",
                        click_image,
                        extra={
                            "good": good,
                            "pos": pos,
                            "buy_pos": buy_pos,
                            "attempt": attempt,
                        },
                    )
                    capture_page_state(
                        "buy_good_click_opened_detail",
                        click_image,
                        extra={
                            "good": good,
                            "pos": pos,
                            "buy_pos": buy_pos,
                            "attempt": attempt,
                        },
                    )
                    continue
                if blocker := get_buy_click_blocker(click_image):
                    if blocker == "无法购买":
                        disable_trade_product_for_city(
                            buy_city_name,
                            good,
                            reason=f"购买点击提示{blocker}",
                        )
                        _raise_replan_required(buy_city_name, good, "无法购买")
                    capture_state(
                        "buy_good_click_blocked",
                        click_image,
                        extra={
                            "good": good,
                            "pos": pos,
                            "buy_pos": buy_pos,
                            "attempt": attempt,
                            "blocker": blocker,
                        },
                    )
                    capture_page_state(
                        "buy_good_click_blocked",
                        click_image,
                        extra={
                            "good": good,
                            "pos": pos,
                            "buy_pos": buy_pos,
                            "attempt": attempt,
                            "blocker": blocker,
                        },
                    )
                    return False, book
                time.sleep(0.35)
                if not is_empty_goods():
                    changed = enable_trade_product_for_city(
                        buy_city_name,
                        good,
                        reason="购买成功",
                    )
                    if changed:
                        _raise_replan_required(buy_city_name, good, "已恢复解锁")
                    return True, book
            capture_state(
                "buy_good_click_no_cart_change",
                extra={"good": good, "pos": pos, "buy_points": buy_points},
            )
            capture_page_state(
                "buy_good_click_no_cart_change",
                extra={"good": good, "pos": pos, "buy_points": buy_points},
            )
            return False, book
    else:
        capture_state("buy_good_not_found", extra={"good": good})
        capture_page_state("buy_good_not_found", extra={"good": good})
        return False, book


def tap_book_confirm() -> None:
    confirm_pos, _ = find_text(
        "确认",
        cropped_pos1=(880, 500),
        cropped_pos2=(1080, 590),
        log=False,
    )
    input_tap(confirm_pos or BOOK_CONFIRM_POINT)


def use_book(pos: Tuple[int, int], book: int, *, count: int = 1):
    """
    说明:
        使用进货书
    """
    count = max(1, min(int(count or 1), BOOK_COUNT_MAX_PER_USE))
    logger.info(f"使用进货书:{book + 1}-{book + count}")
    if not open_book_popup():
        capture_state("buy_use_book_popup_missing", extra={"pos": pos, "book": book, "count": count})
        capture_page_state("buy_use_book_popup_missing", extra={"pos": pos, "book": book, "count": count})
        return False
    for _ in range(count - 1):
        input_tap(BOOK_INCREMENT_POINT)
        time.sleep(0.12)
    tap_book_confirm()
    start = time.perf_counter()
    while time.perf_counter() - start < BOOK_USE_TIMEOUT and (hsv := screenshot().get_hsv(pos))[-1] < 60:
        logger.debug(f"进货书是否所有成功颜色检查: {hsv}")
        time.sleep(0.5)
    if (hsv := screenshot().get_hsv(pos))[-1] < 60:
        capture_state("buy_use_book_timeout", extra={"pos": pos, "book": book})
        capture_page_state("buy_use_book_timeout", extra={"pos": pos, "book": book})
        return False
    return True


def find_good(good, timeout=10, buy_city_name: str | None = None):
    """
    说明:
        查找并点击商品
    """
    pos, image, known_order_done = find_good_by_known_city_order(good, buy_city_name, timeout=min(float(timeout), 8.0))
    if pos:
        return pos, image
    if known_order_done:
        capture_state(
            "buy_find_good_known_order_stop",
            extra={"good": good, "city": buy_city_name, "timeout": timeout},
        )
        capture_page_state(
            "buy_find_good_known_order_stop",
            extra={"good": good, "city": buy_city_name, "timeout": timeout},
        )
        return None, None

    start = time.time()
    last_signature: tuple[str, ...] | None = None
    repeated_signature_count = 0
    while (spend_time := time.time() - start) < timeout:
        close_good_detail_popup()
        if spend_time < timeout / 2:
            input_swipe((678, 558), (693, 314), swipe_time=500)
        else:
            input_swipe((693, 314), (678, 558), swipe_time=500)
        # 等待拖到动画结束
        time.sleep(0.7)
        result, image = find_text(
            good,
            cropped_pos1=(622, 136),
            cropped_pos2=(854, 685),
            log=False,
        )
        if result:
            return result, image
        if buy_city_name:
            signature = _visible_trade_signature(_visible_city_trade_entries(buy_city_name))
            if signature and signature == last_signature:
                repeated_signature_count += 1
            else:
                repeated_signature_count = 0
            last_signature = signature
            if repeated_signature_count >= GOOD_LIST_STUCK_LIMIT:
                logger.warning(
                    "普通商品查找滑动后可见商品未变化，提前停止: "
                    f"city={buy_city_name} target={good} visible={'->'.join(signature)}"
                )
                break
    capture_state("buy_find_good_timeout", extra={"good": good, "timeout": timeout})
    capture_page_state("buy_find_good_timeout", extra={"good": good, "timeout": timeout})
    return None, None


def get_boatload():
    """
    说明:
        获取载货量百分比
    """
    close_good_detail_popup()
    image = screenshot_image()
    lower_color_bound = np.array([35, 35, 35])
    upper_color_bound = np.array([36, 36, 36])

    y = 418
    x_start = 872
    x_end = 1240

    # 获取指定行的指定区间
    row_segment = image[y : y + 1, x_start:x_end]
    # 寻找指定颜色
    mask = cv.inRange(row_segment, lower_color_bound, upper_color_bound)

    boatload = np.sum(mask == 255) / (x_end - x_start)
    return int(boatload * 100)


def read_bargain_percent(image=None) -> int | None:
    image = image or screenshot()
    image.crop_image(HAGGLE_PERCENT_CROP_POS1, HAGGLE_PERCENT_CROP_POS2)
    for item in image.ocr():
        text = str(item.get("text", "")).replace("O", "0").replace("o", "0")
        match = re.search(r"\d{1,3}", text)
        if match:
            return int(match.group())
    return None


def click_bargain_button_of_bargain(target_bargain=0):
    """
    说明:
        点击议价按钮
    参数:
        :param target_bargain: 目标议价百分比
    """
    if target_bargain <= 0:
        return True
    target_bargain = min(int(target_bargain), HAGGLE_PERCENT_LIMIT)
    start = time.perf_counter()
    while time.perf_counter() - start < 15:
        bargain = read_bargain_percent()
        logger.info(f"降价幅度: {bargain}%")
        if bargain is not None and bargain >= target_bargain:
            return True
        if get_excption() == "议价次数不足":
            return False
        bgr = screenshot().get_bgr((1176, 461))
        logger.debug(f"降价界面颜色检查: {bgr}")
        if BGR(5, 135, 245) == bgr:
            input_tap((1177, 461))
            time.sleep(0.5)
        elif bgr == [251, 253, 253]:
            logger.info("议价次数不足")
            return True
        elif bgr == FATIGUE_BLOCKED_BGR:
            if recover_buy_strength("买入砍价", "buy_target_bargain_strength_insufficient"):
                return True
            return False
    capture_state("buy_bargain_target_timeout", extra={"target_bargain": target_bargain})
    capture_page_state("buy_bargain_target_timeout", extra={"target_bargain": target_bargain})
    return False


def click_bargain_button(num=0):
    """
    说明:
        点击议价按钮
    参数:
        :param num: 目标议价幅度百分比
    """
    target_percent = min(int(num or 0), HAGGLE_PERCENT_LIMIT)
    logger.info(f"目标降价幅度: {target_percent}%")
    start = time.perf_counter()
    while time.perf_counter() - start < 15:
        if target_percent <= 0:
            return True
        bargain = read_bargain_percent()
        logger.info(f"当前降价幅度: {bargain}%")
        if bargain is not None and bargain >= target_percent:
            logger.info(f"降价已达到目标 {target_percent}%，停止继续议价")
            return True
        bgr = screenshot().get_bgr((1176, 461))
        logger.debug(f"降价界面颜色检查: {bgr}")
        if BGR(0, 123, 240) <= bgr <= BGR(2, 133, 255):
            input_tap((1177, 461))
            time.sleep(1.0)
        elif bgr == [251, 253, 253]:
            logger.info("降价次数不足")
            return True
        elif bgr == FATIGUE_BLOCKED_BGR:
            if recover_buy_strength("买入砍价", "buy_bargain_strength_insufficient"):
                return True
            return False
        time.sleep(0.5)
    capture_state("buy_bargain_timeout", extra={"target_percent": target_percent})
    capture_page_state("buy_bargain_timeout", extra={"target_percent": target_percent})
    return False


def click_buy_button():
    """
    说明:
        点击购买按钮
    """
    for attempt in range(1, BUY_CONFIRM_ATTEMPTS + 1):
        if is_empty_goods():
            capture_state("buy_confirm_without_selected_goods", extra={"attempt": attempt})
            capture_page_state("buy_confirm_without_selected_goods", extra={"attempt": attempt})
            return False
        input_tap((1056, 647))
        time.sleep(1)
        image = screenshot()
        bgr = image.get_bgr((1177, 459), offset=5)
        logger.debug(f"购买物品界面颜色检查: {bgr}")
        if has_any_text(ocr_texts(image), BUY_REPORT_TEXTS):
            return True
        state = classify_page(image)
        if state.kind == PageKind.BUY_REPORT:
            return True
        if bgr == FATIGUE_BLOCKED_BGR:
            if recover_buy_strength("确认买入", "buy_confirm_strength_insufficient"):
                continue
            return False
        if state.kind in (PageKind.BUY_PAGE, PageKind.GENERIC_POPUP):
            logger.info("买入确认后仍停留在交易界面，可能为行情变动提示，继续确认")
            _ocr_tap_text(("确认", "确定"), cropped_pos1=(880, 450), cropped_pos2=(1080, 640))
            continue
        if bgr != [2, 133, 253] and bgr != [251, 253, 253]:
            time.sleep(0.8)
            if has_any_text(ocr_texts(), BUY_REPORT_TEXTS) or classify_page().kind == PageKind.BUY_REPORT:
                return True
        capture_state("buy_confirm_retry", image, extra={"attempt": attempt, "bgr": list(bgr)})
        capture_page_state("buy_confirm_retry", image, extra={"attempt": attempt, "bgr": list(bgr)})
    capture_state("buy_confirm_attempts_exhausted", extra={"attempts": BUY_CONFIRM_ATTEMPTS})
    capture_page_state("buy_confirm_attempts_exhausted", extra={"attempts": BUY_CONFIRM_ATTEMPTS})
    return False
