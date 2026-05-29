"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-04-05 15:17:19
LastEditTime: 2024-07-08 21:11:34
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

import re
import time

from loguru import logger

from app.common.runtime_status import emit_run_status
from core.control.control import input_swipe, input_tap, screenshot
from core.module.bgr import BGR
from core.preset import find_text
from core.preset.control import wait_gbr
from core.preset.page_state import PageKind, capture_page_state, classify_page, recover_trade_page
from core.utils.runtime_state import capture_state, has_any_text, ocr_texts

SELL_PAGE_TEXTS = ("预计卖出", "全部卖出", "全部出售", "全部取消")
SELL_EMPTY_TEXTS = ("全部卖出", "全部出售")
SELL_CART_TEXTS = ("全部取消",)
SELL_REPORT_TEXTS = ("卖出结算报告", "出售结算报告", "触碰空白区域退出")
SELL_SELECT_ATTEMPTS = 5
SELL_CONFIRM_ATTEMPTS = 5
SELL_GOOD_CLICK_Y_MAX = 620
SELL_GOOD_SAFE_Y_MAX = 585
HAGGLE_PERCENT_LIMIT = 20
HAGGLE_PERCENT_CROP_POS1 = (988, 450)
HAGGLE_PERCENT_CROP_POS2 = (1042, 475)


def ensure_sell_page(label: str = "sell_not_on_page") -> bool:
    state = classify_page()
    if state.kind == PageKind.SELL_PAGE:
        return True
    recovery = recover_trade_page("sell", label=label)
    if recovery.recovered:
        return True
    state = recovery.after
    capture_page_state(
        label,
        extra={
            "expected": PageKind.SELL_PAGE.value,
            "actual": state.kind.value,
            "confidence": state.confidence,
            "suggested_action": state.suggested_action,
        },
    )
    return False


def sell_business(num=0, goods: list[str] | None = None):
    """
    说明:
        出售商品
    参数:
        :param num: 期望议价的价格
        :param goods: 指定商品列表；为空时保持原逻辑，出售全部商品
    """
    if not ensure_sell_page("sell_business_start_not_on_page"):
        return False
    emit_run_status(
        "正在出售商品",
        "正在选择指定商品" if goods else "正在选择全部货物",
        goods=goods or [],
    )
    if goods:
        if not clear_sell_selection():
            return False
        for good in goods:
            if not sell_good(good):
                capture_state("sell_good_failed", extra={"good": good})
                capture_page_state("sell_good_failed", extra={"good": good})
                return False
    else:
        for attempt in range(1, SELL_SELECT_ATTEMPTS + 1):
            image = screenshot()
            if not is_sell_page(image):
                capture_state("sell_not_on_page", image, extra={"attempt": attempt})
                capture_page_state("sell_not_on_page", image, extra={"attempt": attempt})
                return False
            bgr = image.get_bgr((1156, 100))
            logger.debug(f"是否出售货物颜色检查 {bgr}")
            if not is_empty_goods():
                break
            if not (bgr.b == 0 and bgr.g == 0 and 90 <= bgr.r <= 100):
                logger.debug(f"出售全部货物颜色检查 {bgr}")
                input_tap((1187, 103))
                time.sleep(0.5)
        else:
            capture_state("sell_select_all_attempts_exhausted", extra={"attempts": SELL_SELECT_ATTEMPTS})
            capture_page_state("sell_select_all_attempts_exhausted", extra={"attempts": SELL_SELECT_ATTEMPTS})
            return False

    if is_empty_goods():
        logger.error("检测到未成功出售物品")
        capture_state("sell_no_goods_selected")
        capture_page_state("sell_no_goods_selected")
        return False
    else:
        if num > 0:
            emit_run_status("正在议价", f"目标议价成功次数：{num}")
            if not click_bargain_button(num):
                capture_state("sell_bargain_failed", extra={"num": num})
                capture_page_state("sell_bargain_failed", extra={"num": num})
                return False
        emit_run_status("正在确认卖出", "正在提交出售结算")
        if not click_sell_button():
            capture_state("sell_confirm_failed")
            capture_page_state("sell_confirm_failed")
            return False
        time.sleep(0.5)
        return close_sell_report()


def is_sell_page(image=None):
    return has_any_text(ocr_texts(image), SELL_PAGE_TEXTS)


def close_sell_report():
    for attempt in range(1, 4):
        texts = ocr_texts()
        if not has_any_text(texts, SELL_REPORT_TEXTS):
            return True
        input_tap((896, 676))
        time.sleep(0.5)
    capture_state("sell_report_close_failed", extra={"attempts": attempt})
    capture_page_state("sell_report_close_failed", extra={"attempts": attempt})
    return False


def is_empty_goods():
    texts = ocr_texts(cropped_pos1=(860, 80), cropped_pos2=(1260, 170))
    if not texts:
        texts = ocr_texts()
    if has_any_text(texts, SELL_CART_TEXTS):
        return False
    if has_any_text(texts, SELL_EMPTY_TEXTS):
        return True

    capture_state("sell_cart_state_unknown", extra={"texts": texts[:20]})
    capture_page_state("sell_cart_state_unknown", extra={"texts": texts[:20]})
    return True


def clear_sell_selection() -> bool:
    if is_empty_goods():
        return True
    image = screenshot()
    for item in image.ocr():
        if "全部取消" not in item.get("text", "").replace(" ", ""):
            continue
        position = item["position"]
        center_x = int((position[0][0] + position[2][0]) / 2)
        center_y = int((position[0][1] + position[2][1]) / 2)
        input_tap((center_x, center_y))
        time.sleep(0.5)
        return is_empty_goods()
    capture_state("sell_clear_selection_failed", image)
    capture_page_state("sell_clear_selection_failed", image)
    return False


def sell_good_click_points(pos: tuple[int, int]) -> list[tuple[int, int]]:
    candidates = [
        pos,
        (pos[0], pos[1] + 24),
        (807, pos[1] + 62),
    ]
    points: list[tuple[int, int]] = []
    for point in candidates:
        if point in points:
            continue
        if point[1] > SELL_GOOD_CLICK_Y_MAX:
            continue
        points.append(point)
    return points


def sell_good(good: str) -> bool:
    logger.info(f"正在选择出售: {good}")
    emit_run_status("正在选择出售商品", f"正在选择 {good}", goods=[good])
    pos, _ = find_text(
        good,
        cropped_pos1=(622, 136),
        cropped_pos2=(854, 685),
        log=False,
    )
    if not pos:
        pos = find_sell_good(good)
    if pos and pos[1] > SELL_GOOD_SAFE_Y_MAX:
        input_swipe((690, 560), (690, 360), swipe_time=500)
        time.sleep(0.8)
        pos, _ = find_text(
            good,
            cropped_pos1=(622, 136),
            cropped_pos2=(854, 685),
            log=False,
        )
        if not pos:
            pos = find_sell_good(good)
    if not pos:
        capture_state("sell_good_not_found", extra={"good": good})
        capture_page_state("sell_good_not_found", extra={"good": good})
        return False

    for attempt, click_pos in enumerate(sell_good_click_points(pos), start=1):
        input_tap(click_pos)
        time.sleep(0.7)
        if not is_empty_goods():
            return True
        capture_state(
            "sell_good_click_no_selection",
            extra={"good": good, "pos": pos, "click_pos": click_pos, "attempt": attempt},
        )
        capture_page_state(
            "sell_good_click_no_selection",
            extra={"good": good, "pos": pos, "click_pos": click_pos, "attempt": attempt},
        )
    return False


def find_sell_good(good: str, timeout: float = 30.0) -> tuple[int, int] | None:
    start = time.perf_counter()
    scan_step = 0
    while (spend_time := time.perf_counter() - start) < timeout:
        if scan_step < 8:
            input_swipe((700, 620), (700, 170), swipe_time=800)
        else:
            input_swipe((700, 170), (700, 620), swipe_time=800)
        scan_step += 1
        time.sleep(1.0)
        pos, _ = find_text(
            good,
            cropped_pos1=(622, 136),
            cropped_pos2=(854, 685),
            log=False,
        )
        if pos:
            return pos
    capture_state("sell_find_good_timeout", extra={"good": good, "timeout": timeout})
    capture_page_state("sell_find_good_timeout", extra={"good": good, "timeout": timeout})
    return None


def read_raise_percent(image=None) -> int | None:
    image = image or screenshot()
    image.crop_image(HAGGLE_PERCENT_CROP_POS1, HAGGLE_PERCENT_CROP_POS2)
    for item in image.ocr():
        text = str(item.get("text", "")).replace("O", "0").replace("o", "0")
        match = re.search(r"\d{1,3}", text)
        if match:
            return int(match.group())
    return None


def click_bargain_button(num=0):
    """
    说明:
        点击议价按钮
    参数:
        :param num: 议价成功次数
    """
    logger.info(f"议价成功次数: {num}")
    start = time.perf_counter()
    while time.perf_counter() - start < 15:
        if num <= 0:
            return True
        raised_percent = read_raise_percent()
        if raised_percent is not None and raised_percent >= HAGGLE_PERCENT_LIMIT:
            logger.info("抬价已达到20%，停止继续议价")
            return True
        image = screenshot()
        bgr = image.get_bgr((1176, 461))
        logger.debug(f"抬价界面颜色检查: {bgr}")
        if BGR(0, 170, 240) <= bgr <= BGR(5, 185, 255):
            input_tap((1177, 461))
            time.sleep(1.0)
        elif bgr == [251, 253, 253]:
            logger.info("抬价次数不足")
            return True
        elif bgr == [62, 63, 63]:
            logger.info("疲劳不足")
            input_tap((83, 36))
            return True
        image = screenshot()
        image.crop_image((516, 224), (787, 439))
        hsv = image.get_hsv((626, 273))
        logger.debug(f"抬价是否成功颜色检查(HSV): {hsv}")
        if 30 <= hsv[0] <= 40:
            logger.info("抬价成功")
            num -= 1
        else:
            logger.info("抬价失败")
        # 等待降价动画消失
        wait_gbr((629, 101), BGR(30, 50, 65), BGR(40, 60, 75))
    capture_state("sell_bargain_timeout", extra={"remaining_num": num})
    capture_page_state("sell_bargain_timeout", extra={"remaining_num": num})
    return False


def click_sell_button():
    for attempt in range(1, SELL_CONFIRM_ATTEMPTS + 1):
        if is_empty_goods():
            capture_state("sell_confirm_without_selected_goods", extra={"attempt": attempt})
            capture_page_state("sell_confirm_without_selected_goods", extra={"attempt": attempt})
            return False
        input_tap((1056, 647))
        time.sleep(1)
        image = screenshot()
        bgr = image.get_bgr((1175, 470), offset=5)
        logger.debug(f"出售物品界面颜色检查: {bgr}")
        if has_any_text(ocr_texts(image), SELL_REPORT_TEXTS):
            return True
        state = classify_page(image)
        if state.kind == PageKind.SELL_REPORT:
            return True
        if bgr == [227, 131, 82]:
            logger.info("检测到包含本地商品")
            input_tap((975, 498))
            time.sleep(0.5)
        if bgr != [0, 183, 253] and bgr != [227, 131, 82] and bgr != [251, 253, 253]:
            return True
        capture_state("sell_confirm_retry", image, extra={"attempt": attempt, "bgr": list(bgr)})
        capture_page_state("sell_confirm_retry", image, extra={"attempt": attempt, "bgr": list(bgr)})
    capture_state("sell_confirm_attempts_exhausted", extra={"attempts": SELL_CONFIRM_ATTEMPTS})
    capture_page_state("sell_confirm_attempts_exhausted", extra={"attempts": SELL_CONFIRM_ATTEMPTS})
    return False
