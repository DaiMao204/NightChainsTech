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
from app.common.runtime_status import emit_run_status
from auto.run_business.config_updates import (
    disable_trade_product_for_city,
    enable_trade_product_for_city,
)
from core.control.control import input_swipe, input_tap, screenshot, screenshot_image
from core.exception.exception_handling import get_excption
from core.image.image import Image
from core.module.bgr import BGR
from core.module.hsv import HSV
from core.preset import click, find_text, go_home
from core.preset.control import wait_gbr
from core.preset.page_state import PageKind, capture_page_state, classify_page, recover_trade_page
from core.utils.runtime_state import capture_state, has_any_text, ocr_texts

BUY_GOOD_CLICK_X = 807
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
GOOD_DETAIL_TEXTS = ("获取途径", "拥有数量")
GOOD_LOCKED_TEXTS = ("需要解锁", "未解锁", "本城声望达到", "声望达到", "投资方案")
BUY_CLICK_HINT_CROP1 = (420, 285)
BUY_CLICK_HINT_CROP2 = (860, 430)
BUY_CONFIRM_ATTEMPTS = 5
BOOK_USE_TIMEOUT = 10.0
GOOD_DETAIL_CLOSE_POINTS = ((100, 100), (640, 100), (1200, 620))


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


def close_buy_report():
    for attempt in range(1, 4):
        texts = ocr_texts()
        if not has_any_text(texts, BUY_REPORT_TEXTS):
            return True
        input_tap((100, 100))
        time.sleep(0.8)
    capture_state("buy_report_close_failed", extra={"attempts": attempt})
    capture_page_state("buy_report_close_failed", extra={"attempts": attempt})
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
    :param num: 议价的次数
    :param max_book: 最大使用进货书量
    """
    if not ensure_buy_page("buy_business_start_not_on_page"):
        return False

    failed_goods: set[str] = set()

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

    book = 0
    done = False
    for i in range(max_book + 1):
        if done:
            break
        for good in primary_goods:
            if (book := process_goods(book, good)) is True:
                done = True
                break
    for good in secondary_goods:
        if (book := process_goods(book, good)) is True:
            break
    if not is_empty_goods():
        if num > 0:
            emit_run_status("正在议价", f"目标议价成功次数：{num}", current_city=buy_city_name or "")
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
        return True
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
    lower_name_y = pos[1] + 24
    lower_row_y = pos[1] + BUY_GOOD_CLICK_Y_OFFSET
    candidates = [
        (BUY_GOOD_CLICK_X, lower_name_y),
        (BUY_GOOD_CLICK_X, lower_row_y),
        (min(max(pos[0], 700), 835), lower_name_y),
    ]
    points: list[Tuple[int, int]] = []
    for point in candidates:
        if point in points:
            continue
        if point[1] > BUY_GOOD_CLICK_Y_MAX:
            continue
        points.append(point)
    return points


def is_good_locked(good: str, pos: Tuple[int, int]) -> bool:
    row_top = max(120, pos[1] - 55)
    row_bottom = min(690, pos[1] + 90)
    texts = ocr_texts(cropped_pos1=(500, row_top), cropped_pos2=(860, row_bottom))
    if has_any_text(texts, GOOD_LOCKED_TEXTS):
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
        pos, image = find_good(good)  # 点击失败查找并点击商品
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
                pos, image = find_good(good)
        if not pos:
            return False, book
        if is_good_locked(good, pos):
            disable_trade_product_for_city(
                buy_city_name,
                good,
                reason="购买页识别到未解锁提示",
            )
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
                    enable_trade_product_for_city(
                        buy_city_name,
                        good,
                        reason="购买成功",
                    )
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


def use_book(pos: Tuple[int, int], book: int):
    """
    说明:
        使用进货书
    """
    logger.info(f"使用进货书:{book+1}")
    click((pos[0] - 215, pos[1]))
    time.sleep(1.0)
    click((959, 541))
    start = time.perf_counter()
    while time.perf_counter() - start < BOOK_USE_TIMEOUT and (hsv := screenshot().get_hsv(pos))[-1] < 60:
        logger.debug(f"进货书是否所有成功颜色检查: {hsv}")
        time.sleep(0.5)
    if (hsv := screenshot().get_hsv(pos))[-1] < 60:
        capture_state("buy_use_book_timeout", extra={"pos": pos, "book": book})
        capture_page_state("buy_use_book_timeout", extra={"pos": pos, "book": book})
        return False
    return True


def find_good(good, timeout=10):
    """
    说明:
        查找并点击商品
    """
    start = time.time()
    while (spend_time := time.time() - start) < timeout:
        close_good_detail_popup()
        if spend_time < timeout / 2:
            input_swipe((678, 558), (693, 314), swipe_time=500)
        else:
            input_swipe((693, 314), (678, 558), swipe_time=500)
        # 等待拖到动画结束
        time.sleep(1)
        result, image = find_text(
            good,
            cropped_pos1=(622, 136),
            cropped_pos2=(854, 685),
            log=False,
        )
        if result:
            return result, image
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
        elif bgr == [62, 63, 63]:
            logger.info("疲劳不足")
            input_tap((83, 36))
            return True
    capture_state("buy_bargain_target_timeout", extra={"target_bargain": target_bargain})
    capture_page_state("buy_bargain_target_timeout", extra={"target_bargain": target_bargain})
    return False


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
        bargain = read_bargain_percent()
        if bargain is not None and bargain >= HAGGLE_PERCENT_LIMIT:
            logger.info("降价已达到20%，停止继续议价")
            return True
        bgr = screenshot().get_bgr((1176, 461))
        logger.debug(f"降价界面颜色检查: {bgr}")
        if BGR(0, 123, 240) <= bgr <= BGR(2, 133, 255):
            input_tap((1177, 461))
            time.sleep(1.0)
        elif bgr == [251, 253, 253]:
            logger.info("降价次数不足")
            return True
        elif bgr == [62, 63, 63]:
            logger.info("疲劳不足")
            input_tap((83, 36))
            return True
        hsv = screenshot().crop_image((516, 224), (787, 439)).get_hsv((629, 271))
        logger.debug(f"降价是否成功颜色检查(HSV): {hsv}")
        if 95 <= hsv.h <= 105:
            logger.info("降价成功")
            num -= 1
        else:
            logger.info("降价失败")
        # 等待降价动画消失
        wait_gbr((628, 102), BGR(60, 55, 30), BGR(70, 65, 40))
    capture_state("buy_bargain_timeout", extra={"remaining_num": num})
    capture_page_state("buy_bargain_timeout", extra={"remaining_num": num})
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
        if bgr != [2, 133, 253] and bgr != [251, 253, 253]:
            return True
        capture_state("buy_confirm_retry", image, extra={"attempt": attempt, "bgr": list(bgr)})
        capture_page_state("buy_confirm_retry", image, extra={"attempt": attempt, "bgr": list(bgr)})
    capture_state("buy_confirm_attempts_exhausted", extra={"attempts": BUY_CONFIRM_ATTEMPTS})
    capture_page_state("buy_confirm_attempts_exhausted", extra={"attempts": BUY_CONFIRM_ATTEMPTS})
    return False
