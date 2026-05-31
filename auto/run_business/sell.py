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
from auto.module.strength import recover_strength_by_config
from core.control.control import input_swipe, input_tap, screenshot
from core.module.bgr import BGR
from core.preset import find_text
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
SELL_GOOD_NAME_CROP_POS1 = (622, 136)
SELL_GOOD_NAME_CROP_POS2 = (854, 685)
SELL_LIST_STUCK_LIMIT = 2
HAGGLE_PERCENT_LIMIT = 20
HAGGLE_PERCENT_CROP_POS1 = (988, 450)
HAGGLE_PERCENT_CROP_POS2 = (1042, 475)
FATIGUE_BLOCKED_BGR = [62, 63, 63]
SELL_SELECT_ALL_TEXTS = ("全部卖出", "全部出售")


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


def recover_sell_strength(context: str, label: str) -> bool:
    logger.info("疲劳不足")
    capture_state(label)
    capture_page_state(label)
    emit_run_status("体力不足", f"{context}疲劳不足，正在按疲劳设置恢复")
    if not recover_strength_by_config():
        emit_run_status("体力不足", "疲劳恢复失败，跑商已停止")
        return False
    if not ensure_sell_page(f"{label}_after_recovery"):
        emit_run_status("恢复失败", "恢复疲劳后未能回到卖出页面")
        return False
    return True


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
            emit_run_status("正在议价", f"目标抬价幅度：{min(int(num), HAGGLE_PERCENT_LIMIT)}%")
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


def tap_sell_select_all(image=None) -> bool:
    image = image or screenshot()
    for item in image.ocr():
        text = item.get("text", "").replace(" ", "")
        if not any(label in text for label in SELL_SELECT_ALL_TEXTS):
            continue
        position = item["position"]
        center_x = int((position[0][0] + position[2][0]) / 2)
        center_y = int((position[0][1] + position[2][1]) / 2)
        input_tap((center_x, center_y))
        return True
    input_tap((1187, 103))
    return True


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


def select_all_sell_goods(max_attempts: int = SELL_SELECT_ATTEMPTS) -> bool:
    if not is_empty_goods():
        return True
    for attempt in range(1, max_attempts + 1):
        image = screenshot()
        if not is_sell_page(image):
            capture_state("sell_select_all_not_on_page", image, extra={"attempt": attempt})
            capture_page_state("sell_select_all_not_on_page", image, extra={"attempt": attempt})
            return False
        tap_sell_select_all(image)
        time.sleep(0.6)
        if not is_empty_goods():
            return True
    return False


def sell_all_if_any(num: int = 0, *, empty_ok: bool = True) -> bool:
    """Sell all currently selectable cargo, treating empty cargo as success."""
    if not ensure_sell_page("sell_all_if_any_start_not_on_page"):
        return False
    emit_run_status("正在清空货柜", "正在检查是否有遗留货物")
    if not select_all_sell_goods():
        if empty_ok:
            logger.info("未检测到可出售的遗留货物，跳过清空货柜")
            return True
        capture_state("sell_all_if_any_select_failed")
        capture_page_state("sell_all_if_any_select_failed")
        return False

    if num > 0:
        emit_run_status("正在清空货柜", f"遗留货物抬价到 {min(int(num), HAGGLE_PERCENT_LIMIT)}%")
        if not click_bargain_button(num):
            capture_state("sell_all_if_any_bargain_failed", extra={"num": num})
            capture_page_state("sell_all_if_any_bargain_failed", extra={"num": num})
            return False
    emit_run_status("正在清空货柜", "正在出售遗留货物")
    if not click_sell_button():
        capture_state("sell_all_if_any_confirm_failed")
        capture_page_state("sell_all_if_any_confirm_failed")
        return False
    time.sleep(0.5)
    return close_sell_report()


def is_sell_page(image=None):
    return has_any_text(ocr_texts(image), SELL_PAGE_TEXTS)


def close_sell_report():
    for attempt in range(1, 4):
        image = screenshot()
        texts = ocr_texts(image)
        state = classify_page(image)
        if state.kind in (PageKind.BUSINESS_MENU, PageKind.SELL_PAGE, PageKind.BUY_PAGE):
            return True
        if state.kind != PageKind.SELL_REPORT and not has_any_text(texts, SELL_REPORT_TEXTS):
            return True
        input_tap((896, 676))
        time.sleep(0.5)

    image = screenshot()
    texts = ocr_texts(image)
    state = classify_page(image)
    if state.kind in (PageKind.BUSINESS_MENU, PageKind.SELL_PAGE, PageKind.BUY_PAGE):
        return True
    if state.kind != PageKind.SELL_REPORT and not has_any_text(texts, SELL_REPORT_TEXTS):
        return True

    capture_state("sell_report_close_failed", image, extra={"attempts": attempt, "state": state.kind.value})
    capture_page_state("sell_report_close_failed", image, extra={"attempts": attempt, "state": state.kind.value})
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


def visible_sell_goods_signature() -> tuple[str, ...]:
    image = screenshot()
    image.crop_image(SELL_GOOD_NAME_CROP_POS1, SELL_GOOD_NAME_CROP_POS2)
    entries: list[tuple[int, str]] = []
    for item in image.ocr():
        text = str(item.get("text", "")).replace(" ", "").strip()
        if not text:
            continue
        position = item["position"]
        center_y = int((position[0][1] + position[2][1]) / 2)
        entries.append((center_y, text))
    return tuple(text for _, text in sorted(entries, key=lambda item: item[0]))


def sell_good(good: str) -> bool:
    logger.info(f"正在选择出售: {good}")
    emit_run_status("正在选择出售商品", f"正在选择 {good}", goods=[good])
    pos, _ = find_text(
        good,
        cropped_pos1=SELL_GOOD_NAME_CROP_POS1,
        cropped_pos2=SELL_GOOD_NAME_CROP_POS2,
        log=False,
    )
    if not pos:
        pos = find_sell_good(good)
    if pos and pos[1] > SELL_GOOD_SAFE_Y_MAX:
        input_swipe((690, 560), (690, 360), swipe_time=500)
        time.sleep(0.8)
        pos, _ = find_text(
            good,
            cropped_pos1=SELL_GOOD_NAME_CROP_POS1,
            cropped_pos2=SELL_GOOD_NAME_CROP_POS2,
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
    last_signature: tuple[str, ...] | None = None
    last_direction: str | None = None
    stuck_count = 0
    while (spend_time := time.perf_counter() - start) < timeout:
        if scan_step < 8:
            direction = "down"
            input_swipe((700, 620), (700, 170), swipe_time=800)
        else:
            direction = "up"
            input_swipe((700, 170), (700, 620), swipe_time=800)
        scan_step += 1
        time.sleep(0.7)
        pos, _ = find_text(
            good,
            cropped_pos1=SELL_GOOD_NAME_CROP_POS1,
            cropped_pos2=SELL_GOOD_NAME_CROP_POS2,
            log=False,
        )
        if pos:
            return pos
        signature = visible_sell_goods_signature()
        if signature and signature == last_signature and direction == last_direction:
            stuck_count += 1
        else:
            stuck_count = 0
        last_signature = signature
        last_direction = direction
        if stuck_count < SELL_LIST_STUCK_LIMIT:
            continue
        if direction == "down" and scan_step < 8:
            logger.info(
                "卖出商品列表向下滑动后可见商品未变化，判断已到底，提前改为向上查找: "
                f"target={good} visible={'->'.join(signature)}"
            )
            scan_step = 8
            stuck_count = 0
            last_signature = None
            last_direction = None
            continue
        logger.warning(
            "卖出商品列表滑动后可见商品未变化，判断已到边界或卡住，停止继续拖动: "
            f"target={good} direction={direction} visible={'->'.join(signature)}"
        )
        break
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
        :param num: 目标议价幅度百分比
    """
    target_percent = min(int(num or 0), HAGGLE_PERCENT_LIMIT)
    logger.info(f"目标抬价幅度: {target_percent}%")
    start = time.perf_counter()
    while time.perf_counter() - start < 15:
        if target_percent <= 0:
            return True
        raised_percent = read_raise_percent()
        logger.info(f"当前抬价幅度: {raised_percent}%")
        if raised_percent is not None and raised_percent >= target_percent:
            logger.info(f"抬价已达到目标 {target_percent}%，停止继续议价")
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
        elif bgr == FATIGUE_BLOCKED_BGR:
            if recover_sell_strength("卖出抬价", "sell_bargain_strength_insufficient"):
                return True
            return False
        time.sleep(0.5)
    capture_state("sell_bargain_timeout", extra={"target_percent": target_percent})
    capture_page_state("sell_bargain_timeout", extra={"target_percent": target_percent})
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
        if bgr == FATIGUE_BLOCKED_BGR:
            if recover_sell_strength("确认卖出", "sell_confirm_strength_insufficient"):
                continue
            return False
        if bgr == [227, 131, 82]:
            logger.info("检测到包含本地商品")
            input_tap((975, 498))
            time.sleep(0.5)
        if state.kind in (PageKind.SELL_PAGE, PageKind.GENERIC_POPUP):
            logger.info("卖出确认后仍停留在交易界面，可能为行情变动提示，继续确认")
            _ocr_tap_text(("确认", "确定"), cropped_pos1=(880, 450), cropped_pos2=(1080, 640))
            continue
        if bgr != [0, 183, 253] and bgr != [227, 131, 82] and bgr != [251, 253, 253]:
            time.sleep(0.8)
            if has_any_text(ocr_texts(), SELL_REPORT_TEXTS) or classify_page().kind == PageKind.SELL_REPORT:
                return True
        capture_state("sell_confirm_retry", image, extra={"attempt": attempt, "bgr": list(bgr)})
        capture_page_state("sell_confirm_retry", image, extra={"attempt": attempt, "bgr": list(bgr)})
    capture_state("sell_confirm_attempts_exhausted", extra={"attempts": SELL_CONFIRM_ATTEMPTS})
    capture_page_state("sell_confirm_attempts_exhausted", extra={"attempts": SELL_CONFIRM_ATTEMPTS})
    return False
