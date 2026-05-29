"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-04-05 17:24:47
LastEditTime: 2025-02-11 22:14:21
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

import re
import time

from loguru import logger

from core.control.control import input_tap, screenshot
from core.image.ocr import predict
from core.model.config import config
from core.module.bgr import BGR
from core.preset.control import go_home
from core.preset.page_state import (
    PageKind,
    capture_page_state,
    classify_page,
    close_fight_end,
    recover_route_state,
    start_route_fight,
)
from core.utils.runtime_state import capture_state
from core.utils.utils import RESOURCES_PATH

FIGHT_TIME = 300
MAP_WAIT_TIME = 3000
FIGHT_END_TEMPLATE_THRESHOLD = 0.98
TRAVEL_STATUS_OCR_INTERVAL = 5.0
TRAVEL_STATUS_CROP_POS1 = (520, 20)
TRAVEL_STATUS_CROP_POS2 = (760, 145)
ROUTE_EVENT_OCR_INTERVAL = 2.0
ROUTE_EVENT_CROP_POS1 = (850, 210)
ROUTE_EVENT_CROP_POS2 = (1235, 620)
ROUTE_EVENT_ATTACK_TEXTS = ("护卫队迎击",)
ROUTE_EVENT_PANEL_TEXTS = ("敌方等级", "应对方式", "请选择")
ROUTE_EVENT_ATTACK_POINT = (1009, 251)
ROUTE_STATE_MISSING_TIMEOUT = 60.0
FIGHT_STATE_CHECK_INTERVAL = 5.0
AUTO_PICK_INTERVAL = 5.0
AUTO_PICK_MAX_TAPS = 6
ROUTE_COLLISION_TAP_INTERVAL = 2.0
ROUTE_COLLISION_MAX_TAPS = 3

# pick_mask = cv.imread("resources/mask/pick_mask.png", cv.IMREAD_GRAYSCALE)
# _, pick_mask = cv.threshold(pick_mask, 128, 255, cv.THRESH_BINARY)


class STATION:

    def __init__(self, station: bool, is_destine: bool = False) -> None:
        """
        站点类

        :param station: 是否操作成功
        :param is_destine: 是否在目标站点
        :param cur_station: 当前站点
        :param tar_station: 目标站点
        """
        self.station = station
        self.is_destine = is_destine

    def __bool__(self) -> bool:
        return self.station

    @staticmethod
    def _read_travel_status(image) -> tuple[str | None, int | None, bool]:
        """Read the current route status from the modern driving HUD."""
        try:
            result = predict(
                image.image,
                cropped_pos1=TRAVEL_STATUS_CROP_POS1,
                cropped_pos2=TRAVEL_STATUS_CROP_POS2,
            )
        except Exception as exc:
            logger.debug(f"行车状态OCR失败: {exc}")
            return None, None, False

        destination = None
        remaining = None
        cruising = False
        for item in result:
            text = item["text"].replace(" ", "")
            if "目的地" in text:
                destination = re.split(r"[:：]", text, maxsplit=1)[-1] or None
            if "巡航" in text:
                cruising = True

            distance_match = re.search(r"剩余行程[:：]?(\d+)\s*km", text, re.I)
            if distance_match:
                remaining = int(distance_match.group(1))

        return destination, remaining, cruising

    @staticmethod
    def _read_route_event_attack_point(image) -> tuple[int, int] | None:
        """Detect the modern route event panel and return the attack button point."""
        try:
            result = predict(
                image.image,
                cropped_pos1=ROUTE_EVENT_CROP_POS1,
                cropped_pos2=ROUTE_EVENT_CROP_POS2,
            )
        except Exception as exc:
            logger.debug(f"行车事件OCR失败: {exc}")
            return None

        saw_event_panel = False
        for item in result:
            text = item["text"].replace(" ", "")
            if any(keyword in text for keyword in ROUTE_EVENT_ATTACK_TEXTS):
                position = item["position"]
                center_x = int((position[0][0] + position[2][0]) / 2)
                center_y = int((position[0][1] + position[2][1]) / 2)
                return center_x, center_y
            if any(keyword in text for keyword in ROUTE_EVENT_PANEL_TEXTS):
                saw_event_panel = True

        if saw_event_panel:
            return ROUTE_EVENT_ATTACK_POINT
        return None

    def wait(self):
        """
        说明:
            等待进入站点
        """
        if self.station == False:
            logger.error("进入列车行驶状态失败")
            return False
        if self.is_destine:
            return True
        logger.info("进入行车监听")
        if not self.wait_join():
            logger.warning("未检测到行车地图标识，继续使用HUD/颜色状态监听")
        start = time.perf_counter()
        last_status_ocr = 0.0
        last_event_ocr = 0.0
        last_route_state_seen = start
        last_auto_pick = 0.0
        auto_pick_taps = 0
        auto_pick_limit_logged = False
        last_collision_tap = 0.0
        collision_taps = 0
        collision_limit_logged = False
        last_logged_status: tuple[str | None, int | None, bool] | None = None
        while time.perf_counter() - start < MAP_WAIT_TIME:
            image = screenshot()
            now = time.perf_counter()
            current_status: tuple[str | None, int | None, bool] | None = None
            if now - last_status_ocr >= TRAVEL_STATUS_OCR_INTERVAL:
                current_status = self._read_travel_status(image)
                destination, remaining, cruising = current_status
                if destination is not None or remaining is not None or cruising:
                    last_route_state_seen = now
                if current_status != last_logged_status and (
                    destination is not None or remaining is not None
                ):
                    logger.info(
                        f"行车状态: 目的地={destination or '未知'} "
                        f"剩余={remaining if remaining is not None else '未知'}km "
                        f"巡航={'是' if cruising else '否'}"
                    )
                    last_logged_status = current_status
                last_status_ocr = now

            if now - last_event_ocr >= ROUTE_EVENT_OCR_INTERVAL:
                route_event_attack_point = self._read_route_event_attack_point(image)
                last_event_ocr = now
                if route_event_attack_point:
                    last_route_state_seen = now
                    logger.info(f"检测到行车事件，点击护卫队迎击: {route_event_attack_point}")
                    if not self.join_wait_fight(route_event_attack_point):
                        capture_state("station_route_event_fight_failed", image)
                        capture_page_state("station_route_event_fight_failed", image)
                        return False
                    continue

            if now - last_route_state_seen > ROUTE_STATE_MISSING_TIMEOUT:
                capture_state(
                    "station_wait_route_state_missing",
                    image,
                    extra={"missing_seconds": round(now - last_route_state_seen, 1)},
                )
                state = capture_page_state(
                    "station_wait_route_state_missing",
                    image,
                    extra={"missing_seconds": round(now - last_route_state_seen, 1)},
                )
                recovery = recover_route_state(
                    (
                        PageKind.ROUTE,
                        PageKind.FIGHT,
                        PageKind.FIGHT_END,
                        PageKind.MAIN_MAP,
                        PageKind.CITY,
                        PageKind.BUSINESS_MENU,
                    ),
                    label="station_wait_route_state_missing_recover",
                    max_steps=2,
                )
                state = recovery.after
                logger.info(
                    f"行车状态恢复: before={recovery.before.kind.value} "
                    f"after={state.kind.value} action={recovery.action}"
                )
                if state.kind == PageKind.ROUTE:
                    last_route_state_seen = now
                    continue
                if state.kind == PageKind.FIGHT:
                    if not self.wait_fight_end():
                        return False
                    last_route_state_seen = time.perf_counter()
                    continue
                if state.kind == PageKind.FIGHT_END:
                    logger.info("行车状态恢复后检测到战斗结束页，点击关闭")
                    close_fight_end()
                    last_route_state_seen = time.perf_counter()
                    continue
                if state.kind in (PageKind.MAIN_MAP, PageKind.CITY, PageKind.BUSINESS_MENU):
                    logger.warning(f"行车状态丢失但已回到已知页面 {state.kind.value}，按到站处理")
                    return True
                return False

            # 0-2攻击检测，3-4拦截检测
            attack_bgrs = image.get_bgrs(
                [(944, 247), (967, 229), (1056, 229), (1120, 312)]
            )
            reach_bgrs = image.get_bgrs(
                [(839, 354), (814, 359), (1051, 641), (658, 690)]
            )
            run_bgr = image.get_bgr((1189, 695))
            logger.debug(f"行车攻击检测: {attack_bgrs}")
            logger.debug(f"行车检测: {reach_bgrs}")
            logger.debug(f"是否进站检测: {run_bgr}")
            if (
                BGR(8, 168, 234) <= attack_bgrs[0] <= BGR(10, 171, 245)
                and BGR(8, 168, 234) <= attack_bgrs[1] <= BGR(10, 171, 245)
                and BGR(8, 168, 234) <= attack_bgrs[2] <= BGR(10, 171, 245)
            ):
                logger.info("检测到拦截，进行攻击")
                if not self.join_wait_fight():
                    capture_state("station_color_fight_failed", image)
                    capture_page_state("station_color_fight_failed", image)
                    return False
            elif (
                BGR(9, 167, 235) == attack_bgrs[3]
            ):
                if (
                    collision_taps < ROUTE_COLLISION_MAX_TAPS
                    and now - last_collision_tap >= ROUTE_COLLISION_TAP_INTERVAL
                ):
                    logger.info("检测到可撞击")
                    input_tap((1120, 312))
                    last_collision_tap = now
                    collision_taps += 1
                elif collision_taps >= ROUTE_COLLISION_MAX_TAPS and not collision_limit_logged:
                    logger.warning("行车可撞击点击已达到上限，停止继续点击")
                    collision_limit_logged = True
            elif (
                BGR(20, 20, 20) <= reach_bgrs[0] <= BGR(25, 25, 25)
                and BGR(250, 250, 250) <= reach_bgrs[1] <= BGR(255, 255, 255)
            ):
                logger.info("站点到达")
                input_tap((877, 359))
                # go_home()
                return True
            elif BGR(0, 174, 243) == run_bgr:
                logger.info("站点到达")
                return True
            elif (
                reach_bgrs[2] == [251, 253, 253]
                and reach_bgrs[2] < BGR(235, 235, 250) 
                and reach_bgrs[2] > BGR(240, 240, 255)
                and config.global_config.is_speed
            ):
                logger.info("点击加速弹丸")
                input_tap((1061, 657))
                time.sleep(0.5)
            if (
                config.global_config.is_auto_pick
                and current_status
                and current_status[2]
                and now - last_auto_pick >= AUTO_PICK_INTERVAL
                and auto_pick_taps < AUTO_PICK_MAX_TAPS
            ):
                input_tap((781, 484))  # 捡垃圾
                last_auto_pick = now
                auto_pick_taps += 1
            elif (
                config.global_config.is_auto_pick
                and auto_pick_taps >= AUTO_PICK_MAX_TAPS
                and not auto_pick_limit_logged
            ):
                logger.warning("自动拾取点击已达到本次行程上限，停止继续点击")
                auto_pick_limit_logged = True
            time.sleep(0.3)
        logger.error("站点超时")
        capture_state("station_wait_timeout", extra={"timeout": MAP_WAIT_TIME})
        capture_page_state("station_wait_timeout", extra={"timeout": MAP_WAIT_TIME})
        return False

    def wait_join(self):
        """
        说明:
            等待进入行车地图
        """
        logger.info("等待进入行车地图")
        start = time.perf_counter()
        while time.perf_counter() - start < 10:
            image = screenshot()
            image.crop_image((1032, 621), (1123, 708))
            retult = image.match_template(RESOURCES_PATH / "stations/speed_up.png", 0.95)
            if retult:
                return True
            time.sleep(0.5)
        return False

    def join_wait_fight(self, attack_point: tuple[int, int] | None = None):
        """
        说明:
            进入并等待攻击结束
        """
        result = start_route_fight(
            attack_point or ROUTE_EVENT_ATTACK_POINT,
            label="station_join_fight",
        )
        if not result.handled:
            capture_page_state(
                "station_join_fight_start_failed",
                extra={"action": result.action, "state": result.state.kind.value},
            )
            return False
        logger.info(
            f"行车战斗启动结果: state={result.state.kind.value} "
            f"action={result.action} wait_fight={result.should_wait_fight}"
        )
        if result.state.kind == PageKind.FIGHT_END:
            close_fight_end()
            return True
        if not result.should_wait_fight:
            return True

        return self.wait_fight_end()

    def wait_fight_end(self):
        """
        说明:
            从当前战斗页等待战斗结束
        """
        # 等待战斗结束
        start = time.perf_counter()
        auto_battle_clicked = False
        last_state_check = 0.0
        while time.perf_counter() - start < FIGHT_TIME:
            image = screenshot()
            now = time.perf_counter()
            if now - last_state_check >= FIGHT_STATE_CHECK_INTERVAL:
                state = classify_page(image)
                if state.kind == PageKind.FIGHT_END:
                    logger.info("页面状态检测到战斗结束")
                    close_fight_end(image)
                    return True
                if state.kind == PageKind.ROUTE:
                    logger.info("页面状态检测到已返回行车")
                    return True
                if state.kind in (PageKind.MAIN_MAP, PageKind.CITY, PageKind.BUSINESS_MENU):
                    logger.info(f"页面状态检测到已离开战斗: {state.kind.value}")
                    return True
                last_state_check = now

            bgrs = image.get_bgrs([(1114, 630), (1204, 624), (159, 26)])
            logger.debug(f"战斗检测: {bgrs}")
            if (
                BGR(198, 200, 200) <= bgrs[0] <= BGR(202, 204, 204)
                and BGR(183, 185, 185) <= bgrs[1] <= BGR(187, 189, 189)
            ):
                logger.info("检测到执照等级提升")
                input_tap((1151, 626))
            elif image.crop_image((1137, 566), (1224, 652)).match_template(
                RESOURCES_PATH / "fight/end_fight.png", FIGHT_END_TEMPLATE_THRESHOLD
            ):
                logger.info("战斗结束")
                time.sleep(1.5)
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
            elif bgrs[2] == [126, 126, 126] and not auto_battle_clicked:
                logger.info("开启自动战斗")
                input_tap((159, 44))
                auto_battle_clicked = True
            time.sleep(3)
        logger.error("战斗超时")
        capture_state("station_fight_wait_timeout", extra={"timeout": FIGHT_TIME})
        capture_page_state("station_fight_wait_timeout", extra={"timeout": FIGHT_TIME})
        return False
