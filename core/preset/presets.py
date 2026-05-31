"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-04-05 17:24:47
LastEditTime: 2025-02-11 19:26:36
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

import time
from typing import Dict, Optional, Tuple

import cv2 as cv
import numpy as np
from loguru import logger

from core.control.control import (
    input_swipe,
    input_tap,
    screenshot,
    screenshot_image,
    wait_stopped,
)
from core.module.bgr import BGR
from core.image.ocr import predict
from core.preset import blurry_ocr_click, go_home
from core.preset.page_state import capture_page_state
from core.utils.runtime_state import capture_state
from core.utils.utils import RESOURCES_PATH, read_json

from .control import click_image, ocr_click
from .map_navigation import (
    MapNavigationError,
    open_station_map_from_home,
    select_station_on_map,
)
from .station import STATION

FIGHT_TIME = 1000
FIGHT_END_TEMPLATE_THRESHOLD = 0.98

STATION_NAME2PNG: Dict[str, str] = read_json(RESOURCES_PATH / "stations/name2id.json")

# 站点坐标，左上角为(0, 0)
# STATION_POS_DATA = {
#     "澄明数据中心": (1049, 345),
#     "7号自由港": (665, 577),
#     "阿妮塔战备工厂": (832, 664),
#     "阿妮塔发射中心": (164, 420 + 577),
#     "阿妮塔能源研究所": (614, 454 + 577),
#     "修格里城": (285 + 1049, 121 + 345),
#     "铁盟哨站": (501 + 1049, 122 + 345),
#     "荒原站": (753 + 1049, 121 + 345),
#     "曼德矿场": (602 + 1049, 322 + 345),
#     "淘金乐园": (701 + 1049, 604 + 345),
#     "海角城": (164 + 293, 420 + 577 + 569),
# }
STATION_POS_DATA: Dict[str, Tuple[int, int]] = read_json(
    RESOURCES_PATH / "goods/CityPosData.json"
)


def calculate_station_differences(station_map_data: dict):
    differences = {}
    for site1, coords1 in station_map_data.items():
        for site2, coords2 in station_map_data.items():
            if site1 != site2:
                x_diff = coords2[0] - coords1[0]
                y_diff = coords1[1] - coords2[1]
                differences[(site1, site2)] = (x_diff, y_diff)
    return differences


# 计算站点之间的差值
STATION_DIFFERENCES = calculate_station_differences(STATION_POS_DATA)
GO_CITY_ATTEMPTS = 8
OUTLET_AVATAR_FALLBACK_Y_OFFSET = 65
OUTLET_AVATAR_MIN_DY = 25
OUTLET_AVATAR_MAX_DY = 135
OUTLET_AVATAR_MAX_DX = 170


def click_station(name: str, cur_station: Optional[str] = None):
    """
    点击站点

    :param name: 目标站点
    :param cur_station: 当前站点
    """
    logger.info(f"点击站点 => {name}")
    if cur_station and name == cur_station:
        logger.info("已在目标站点")
        return STATION(True, is_destine=True)
    if screenshot().match_template(RESOURCES_PATH / "main_map.png", 0.95) == False:
        logger.info("未检测到主地图界面，返回主地图")
        if not go_home():
            capture_page_state("click_station_go_home_failed", extra={"target": name})
            return STATION(False)
    logger.info("检测到主地图界面，识别站点")
    if not cur_station:
        station = get_station(is_go_home=False)
    else:
        station = cur_station
    if name == station:
        logger.info("已在目标站点")
        return STATION(True, is_destine=True)

    if not go_home():
        capture_page_state("click_station_prepare_map_failed", extra={"target": name})
        return STATION(False)
    try:
        open_station_map_from_home()
        probe = select_station_on_map(
            name,
            travel=True,
            current_station=station,
            coordinate_first=True,
            route_first=False,
            fallback_scan=True,
        )
    except MapNavigationError as exc:
        logger.error(f"站点导航失败: {exc}")
        capture_page_state(
            "click_station_navigation_failed",
            extra={"target": name, "current_station": station, "error": str(exc)},
        )
        return STATION(False)

    if probe:
        return STATION(True)

    logger.error(f"未能确认目标站点: {name}")
    return STATION(False)


def get_station(is_go_home: bool = True):
    """
    获取当前站点

    :param is_go_home: 是否返回主界面
    """
    go_home()
    input_tap((1170, 493))
    time.sleep(1.0)
    reslut = predict(
        screenshot_image(), cropped_pos1=(166, 520), cropped_pos2=(470, 600)
    )
    if len(reslut) == 0:
        capture_state("get_station_ocr_empty")
        capture_page_state("get_station_ocr_empty")
        raise ValueError("未识别到当前城市")
    logger.info(f"当前站点: {reslut[0]['text']}")
    if is_go_home:
        # 返回主界面，回溯进入城市地图操作
        go_home()
    return reslut[0]["text"]


def go_city():
    """
    说明:
        进入城市界面
    """
    for attempt in range(1, GO_CITY_ATTEMPTS + 1):
        if (
            screenshot()
            .crop_image(cropped_pos1=(25, 634), cropped_pos2=(99, 707))
            .match_template(RESOURCES_PATH / "fame.png", 0.95)
        ):
            return True
        input_tap((1270, 494))
        time.sleep(2.0)
    capture_state("go_city_attempts_exhausted", extra={"attempts": GO_CITY_ATTEMPTS})
    capture_page_state("go_city_attempts_exhausted", extra={"attempts": GO_CITY_ATTEMPTS})
    return False


def _text_center(position) -> tuple[int, int]:
    return (
        int((position[0][0] + position[2][0]) / 2),
        int((position[0][1] + position[2][1]) / 2),
    )


def _matches_outlet_name(text: str, name: str, score: float = 0.65) -> bool:
    text = text.replace(" ", "")
    name = name.replace(" ", "")
    if name in text:
        return True
    return len(name) / max(len(text), 1) >= score and text in name


def _outlet_avatar_circles(raw) -> list[tuple[int, int, int]]:
    gray = cv.cvtColor(raw, cv.COLOR_BGR2GRAY)
    gray = cv.medianBlur(gray, 5)
    circles = cv.HoughCircles(
        gray,
        cv.HOUGH_GRADIENT,
        dp=1.2,
        minDist=80,
        param1=80,
        param2=32,
        minRadius=35,
        maxRadius=72,
    )
    if circles is None:
        return []
    return [tuple(map(int, circle)) for circle in np.round(circles[0]).astype(int)]


def find_outlet_avatar_click_point(name: str, image=None) -> tuple[int, int] | None:
    """Find the circular building portrait under a city building name."""
    image = image or screenshot()
    raw = image.image
    for item in image.ocr():
        if not _matches_outlet_name(item.get("text", ""), name):
            continue
        text_x, text_y = _text_center(item["position"])
        candidates = []
        for circle_x, circle_y, radius in _outlet_avatar_circles(raw):
            dx = abs(circle_x - text_x)
            dy = circle_y - text_y
            if dx > OUTLET_AVATAR_MAX_DX or not (OUTLET_AVATAR_MIN_DY <= dy <= OUTLET_AVATAR_MAX_DY):
                continue
            score = dx * 1.2 + abs(dy - OUTLET_AVATAR_FALLBACK_Y_OFFSET) * 0.8
            candidates.append((score, circle_x, circle_y, radius))
        if candidates:
            _, circle_x, circle_y, radius = min(candidates, key=lambda item: item[0])
            logger.debug(f"建筑头像点击点: {name} -> {(circle_x, circle_y)} radius={radius}")
            return circle_x, circle_y
        return text_x, text_y + OUTLET_AVATAR_FALLBACK_Y_OFFSET
    return None


def click_outlet_avatar(name: str, trynum: int = 3) -> bool:
    for _ in range(trynum):
        image = screenshot()
        point = find_outlet_avatar_click_point(name, image)
        if point:
            input_tap(point)
            return True
        time.sleep(1)
    return False


def go_outlets(name: str):
    """
    前往指定门店

    :param name: 门店名称
    """
    if not go_city():
        return False
    logger.info(f"前往 => {name}")
    if result := click_outlet_avatar(name):
        return result
    if result := blurry_ocr_click(name, excursion_pos=(0, OUTLET_AVATAR_FALLBACK_Y_OFFSET), log=False):
        return result
    input_swipe((457, 340), (457, 369), swipe_time=500)
    if result := click_outlet_avatar(name, trynum=1):
        return result
    if result := ocr_click(name, excursion_pos=(0, OUTLET_AVATAR_FALLBACK_Y_OFFSET), log=False):
        return result
    input_swipe((400, 340), (457, 340), swipe_time=500)
    if result := click_outlet_avatar(name, trynum=1):
        return result
    if result := ocr_click(name, excursion_pos=(0, OUTLET_AVATAR_FALLBACK_Y_OFFSET), log=False):
        return result
    input_swipe((969, 369), (457, 340), swipe_time=500)
    if result := click_outlet_avatar(name, trynum=1):
        return result
    if result := ocr_click(name, excursion_pos=(0, OUTLET_AVATAR_FALLBACK_Y_OFFSET), log=False):
        return result
    input_swipe((641, 246), (637, 615), swipe_time=500)
    if result := click_outlet_avatar(name, trynum=1):
        return result
    if result := ocr_click(name, excursion_pos=(0, OUTLET_AVATAR_FALLBACK_Y_OFFSET)):
        return result
    capture_state("go_outlets_not_found", extra={"name": name})
    capture_page_state("go_outlets_not_found", extra={"name": name})
    return False

def go_shop():
    """
    前往交易所
    """
    result = click_image(RESOURCES_PATH / "shop" / "1.png", trynum=1, check_err=False)
    if not result:
        capture_page_state("go_shop_not_found")
    return result

def wait_fight_end():
    """
    说明:
        等待战斗结束
    """
    logger.info("等待战斗结束")
    start = time.perf_counter()
    auto_battle_clicked = False
    while time.perf_counter() - start < FIGHT_TIME:
        image = screenshot()
        bgrs = image.get_bgrs([(1114, 630), (1204, 624), (167, 29)])
        logger.debug(f"等待战斗结束颜色检查: {bgrs}")
        if (
            BGR(198, 200, 200) <= bgrs[0] <= BGR(202, 204, 204) 
            and BGR(183, 185, 185) <= bgrs[1] <= BGR(187, 189, 189)
        ):
            logger.info("检测到执照等级提升")
            input_tap((1151, 626))
            continue
        elif image.crop_image((1070, 600), (1251, 670)).match_template(
            RESOURCES_PATH / "fight/end_fight.png", FIGHT_END_TEMPLATE_THRESHOLD
        ):
            logger.info("战斗结束")
            time.sleep(1.0)
            input_tap((1151, 626))
            return True
        # elif (
        #     BGRGroup([245, 245, 245], [255, 255, 255]) == bgrs[0]
        #     and BGRGroup([9, 9, 9], [10, 10, 10]) == bgrs[3]
        # ):
        #     logger.info("战斗失败")
        #     time.sleep(1.0)
        #     input_tap((1151, 626))
        #     return True
        elif bgrs[2] == [124, 126, 125] and not auto_battle_clicked:
            logger.info("开启自动战斗")
            input_tap((233, 44))
            auto_battle_clicked = True
        time.sleep(3)
    logger.error("战斗超时")
    capture_state("wait_fight_end_timeout", extra={"timeout": FIGHT_TIME})
    capture_page_state("wait_fight_end_timeout", extra={"timeout": FIGHT_TIME})
    return False
