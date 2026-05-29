"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-04-05 17:14:29
LastEditTime: 2025-02-11 19:26:08
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

import time
from typing import Any, Dict, Literal

from loguru import logger

from app.common.runtime_status import emit_run_status
import core.control.control as control_state
from auto.module.strength import check_shop_strength, recover_strength_by_config
from auto.run_business.buy import buy_business
from auto.run_business.sell import sell_business
from auto.run_business.status_fields import routes_profit_status_fields
from core.control.control import STOP, connect, input_tap, screenshot
from core.model import app
from core.model.city_goods import RouteModel, RoutesModel
from core.module.bgr import BGR
from core.preset import click_station, get_station, go_home, go_outlets, wait_gbr
from core.preset.page_state import (
    PageKind,
    capture_page_state,
    classify_page,
    recover_trade_page,
    restart_game_to_main,
    wait_for_page_state,
)
from core.utils.runtime_state import capture_state, has_any_text, ocr_texts
from core.utils.utils import read_json, RESOURCES_PATH

_city_sell_data: Any = read_json(RESOURCES_PATH / "goods/CityGoodsSellData.json")
city_sell_data = {
    city: dict(sorted(goods.items(), key=lambda item: item[1]["price"], reverse=True))
    for city, goods in _city_sell_data.items()
}
_fatigue_data: Any = read_json(RESOURCES_PATH / "goods/CityFatigueData2026.json")
city_fatigue_map: dict[str, int] = (
    _fatigue_data.get("map", {}) if isinstance(_fatigue_data, dict) else {}
)

BUY_PAGE_TEXTS = ("预计买入", "全部买入", "全部取消")
SELL_PAGE_TEXTS = ("预计卖出", "全部卖出", "全部出售", "全部取消")
BUSINESS_MENU_TEXTS = ("交易所", "我要买", "我要卖")
BUSINESS_ENTRY_ATTEMPTS = 3
RUN_FAILURE_RECOVERY_TIMEOUT = 90.0


def reset_game_after_run_failure(label: str, extra: dict[str, Any] | None = None) -> None:
    logger.warning(f"跑商流程失败，尝试重启游戏恢复到主地图: {label}")
    recovery = restart_game_to_main(
        label=f"{label}_restart",
        timeout=RUN_FAILURE_RECOVERY_TIMEOUT,
    )
    capture_page_state(
        f"{label}_restart_final",
        extra={
            "recovered": recovery.recovered,
            "action": recovery.action,
            "steps": recovery.steps,
            "extra": extra or {},
        },
    )
    if not recovery.recovered:
        logger.warning(f"重启后仍未回到主地图: {recovery.after.kind.value}")


def is_business_page(type: Literal["buy", "sell"] = "buy"):
    texts = ocr_texts()
    if type == "buy":
        return has_any_text(texts, BUY_PAGE_TEXTS)
    return has_any_text(texts, SELL_PAGE_TEXTS)


def click_business_menu_option(type: Literal["buy", "sell"] = "buy") -> bool:
    option_text = "我要买" if type == "buy" else "我要卖"
    for attempt in range(1, BUSINESS_ENTRY_ATTEMPTS + 1):
        image = screenshot()
        data = image.ocr()
        texts = [item["text"].replace(" ", "") for item in data]
        if not has_any_text(texts, BUSINESS_MENU_TEXTS):
            return False
        for item in data:
            if option_text not in item["text"].replace(" ", ""):
                continue
            position = item["position"]
            center_x = int((position[0][0] + position[2][0]) / 2)
            center_y = int((position[0][1] + position[2][1]) / 2)
            input_tap((center_x, center_y))
            time.sleep(1.0)
            if is_business_page(type):
                return True
            capture_state(
                f"go_business_menu_{type}_retry_{attempt}",
                extra={"attempt": attempt, "option": option_text},
            )
            break
    return False


def show(routes: RoutesModel):
    route = routes.city_data
    message = f"""{route[0].buy_city_name}<->{route[0].sell_city_name}:
{route[0].buy_city_name}:
    商品顺序: {"->".join(route[0].goods_data.keys())}
    议价成功次数: {route[0].haggle_num}
    书本数量: {route[0].book}
{route[0].sell_city_name}:
    商品顺序: {"->".join(route[1].goods_data.keys())}
    议价成功次数: {route[1].haggle_num}
    书本数量: {route[1].book}"""

    return message


def _routes_text(routes: RoutesModel) -> str:
    legs = routes.city_data or []
    if not legs:
        return ""
    cities = [leg.buy_city_name for leg in legs]
    if legs[-1].sell_city_name:
        cities.append(legs[-1].sell_city_name)
    return " -> ".join(city for city in cities if city)


def _route_goods(route: RouteModel) -> list[str]:
    return list(route.goods_data.keys())


def city_fatigue_between(from_city: str, to_city: str) -> int:
    if from_city == to_city:
        return 0
    return int(
        city_fatigue_map.get(f"{from_city}-{to_city}")
        or city_fatigue_map.get(f"{to_city}-{from_city}")
        or 9999
    )


def reorder_route_by_current_city(routes: RoutesModel, city_name: str) -> bool:
    if len(routes.city_data) < 2:
        return False
    first, second = routes.city_data[0], routes.city_data[1]
    start_a = first.buy_city_name
    start_b = second.buy_city_name
    if city_name == start_b:
        routes.city_data = [second, first]
        return True
    if city_name == start_a:
        return False

    fatigue_to_a = city_fatigue_between(city_name, start_a)
    fatigue_to_b = city_fatigue_between(city_name, start_b)
    logger.info(
        f"当前城市到路线两端疲劳: {city_name}->{start_a}={fatigue_to_a}, "
        f"{city_name}->{start_b}={fatigue_to_b}"
    )
    if fatigue_to_b < fatigue_to_a:
        routes.city_data = [second, first]
        return True
    return False


def go_business(type: Literal["buy", "sell"] = "buy"):
    logger.info("前往交易所")
    target_page = PageKind.BUY_PAGE if type == "buy" else PageKind.SELL_PAGE
    wrong_page = PageKind.SELL_PAGE if type == "buy" else PageKind.BUY_PAGE
    state = classify_page()
    logger.info(
        f"当前页面状态: {state.kind.value} "
        f"confidence={state.confidence} action={state.suggested_action}"
    )
    recovery = recover_trade_page(
        type,
        label=f"go_business_{type}_precheck",
        capture_on_blocked=False,
    )
    if recovery.recovered:
        return True
    state = recovery.after
    if state.kind in (PageKind.BUY_REPORT, PageKind.SELL_REPORT):
        capture_page_state("go_business_close_report_before_entry", extra={"type": type})
        input_tap((100, 100))
        time.sleep(1.0)
        state = classify_page()
        if state.kind == target_page:
            return True
    if state.kind == wrong_page:
        capture_page_state("go_business_wrong_trade_page", extra={"type": type})
        go_home()
    if state.kind == PageKind.BUSINESS_MENU and click_business_menu_option(type):
        return True
    if click_business_menu_option(type):
        return True

    result = go_outlets("交易所")
    is_join = wait_gbr(
        pos=(286, 35),
        min_gbr=BGR(250, 250, 250),
        max_gbr=BGR(255, 255, 255),
        cropped_pos1=(242, 11),
        cropped_pos2=(414, 66),
    )
    if result and is_join:
        recovery = recover_trade_page(type, label=f"go_business_{type}_from_menu")
        if recovery.recovered:
            return True
        tap_pos = (927, 321) if type == "buy" else (932, 404)
        for attempt in range(1, BUSINESS_ENTRY_ATTEMPTS + 1):
            input_tap(tap_pos)
            time.sleep(1.0)
            image = screenshot()
            bgr = image.get_bgr((1175, 460))
            logger.debug(f"进入交易所颜色检查: {bgr}")
            if (
                BGR(0, 123, 240) <= bgr <= BGR(2, 133, 255)
                or BGR(225, 225, 225) == bgr
                or BGR(0, 170, 240) <= bgr <= BGR(5, 185, 255)
            ):
                return True
            if is_business_page(type):
                logger.info("已通过OCR确认进入交易所")
                return True
            page_state = wait_for_page_state(
                target_page,
                timeout=1.0,
                interval=0.3,
                label=None,
            )
            if page_state.kind == target_page:
                logger.info("已通过页面状态确认进入交易所")
                return True
            capture_state(
                f"go_business_{type}_retry_{attempt}",
                image,
                extra={"attempt": attempt, "bgr": list(bgr)},
            )
            capture_page_state(
                f"go_business_{type}_retry_{attempt}",
                image,
                extra={"attempt": attempt, "bgr": list(bgr)},
            )
        logger.error("进入交易所失败")
        capture_page_state(f"go_business_{type}_failed", extra={"type": type})
        return False
    else:
        capture_state(
            "go_business_outlet_failed",
            extra={"type": type, "outlet": bool(result), "joined": bool(is_join)},
        )
        capture_page_state(
            "go_business_outlet_failed",
            extra={"type": type, "outlet": bool(result), "joined": bool(is_join)},
        )
        logger.error("进入交易所失败")
        return False


def ensure_trade_strength(route_text: str, profit_fields: dict[str, Any]) -> bool:
    if check_shop_strength():
        return True
    emit_run_status(
        "体力不足",
        "正在按疲劳设置尝试恢复体力",
        route=route_text,
        **profit_fields,
    )
    if recover_strength_by_config():
        return True
    emit_run_status(
        "体力不足",
        "未能恢复体力，跑商已停止",
        route=route_text,
        **profit_fields,
    )
    return False


def run(routes: RoutesModel):
    logger.info(show(routes))
    route_text = _routes_text(routes)
    profit_fields = routes_profit_status_fields(routes)
    emit_run_status(
        "准备连接游戏",
        "正在连接模拟器并确认当前位置",
        route=route_text,
        **profit_fields,
    )
    status = connect()
    if not status:
        logger.error("ADB连接失败")
        emit_run_status("连接失败", "ADB连接失败", route=route_text, **profit_fields)
        return False
    city_name = get_station()
    if reorder_route_by_current_city(routes, city_name):
        route_text = _routes_text(routes)
        profit_fields = routes_profit_status_fields(routes)
    for city in routes.city_data:
        logger.info(f"{city.buy_city_name}->{city.sell_city_name}")
        goods_data = list(city.goods_data.keys())
        emit_run_status(
            "正在前往买入城市",
            f"准备在 {city.buy_city_name} 购买商品",
            route=route_text,
            target_city=city.buy_city_name,
            goods=goods_data,
            **profit_fields,
        )
        if not click_station(city.buy_city_name, cur_station=city_name).wait():
            emit_run_status(
                "前往买入城市失败",
                f"未能到达 {city.buy_city_name}，正在尝试恢复",
                route=route_text,
                target_city=city.buy_city_name,
                **profit_fields,
            )
            capture_state("run_wait_buy_city_failed", extra={"target": city.buy_city_name})
            capture_page_state("run_wait_buy_city_failed", extra={"target": city.buy_city_name})
            reset_game_after_run_failure("run_wait_buy_city_failed", {"target": city.buy_city_name})
            return False
        city_name = city.buy_city_name
        emit_run_status(
            "正在打开交易所",
            f"已到达 {city_name}，正在进入买入页面",
            route=route_text,
            current_city=city_name,
            **profit_fields,
        )
        if not go_business("buy"):
            emit_run_status(
                "打开买入页面失败",
                f"{city_name} 交易所买入页面打开失败，正在恢复",
                route=route_text,
                current_city=city_name,
                **profit_fields,
            )
            capture_state("run_open_buy_failed", extra={"city": city_name})
            capture_page_state("run_open_buy_failed", extra={"city": city_name})
            reset_game_after_run_failure("run_open_buy_failed", {"city": city_name})
            return False
        if not ensure_trade_strength(route_text, profit_fields):
            return False
        emit_run_status(
            "正在购买商品",
            f"正在 {city.buy_city_name} 购买推荐商品",
            route=route_text,
            current_city=city.buy_city_name,
            goods=goods_data,
            **profit_fields,
        )
        if not buy_business(
            goods_data[:1],
            goods_data[1:],
            city.haggle_num,
            max_book=city.book,
            buy_city_name=city.buy_city_name,
        ):
            emit_run_status(
                "购买失败",
                f"{city.buy_city_name} 商品购买失败，正在尝试恢复",
                route=route_text,
                current_city=city.buy_city_name,
                goods=goods_data,
                **profit_fields,
            )
            capture_state("run_buy_business_failed", extra={"city": city_name})
            capture_page_state("run_buy_business_failed", extra={"city": city_name})
            reset_game_after_run_failure("run_buy_business_failed", {"city": city_name})
            return False
        emit_run_status(
            "购买完成",
            f"{city.buy_city_name} 进货完成，准备前往 {city.sell_city_name}",
            route=route_text,
            current_city=city.buy_city_name,
            target_city=city.sell_city_name,
            **profit_fields,
        )
        emit_run_status(
            "正在前往卖出城市",
            f"正在前往 {city.sell_city_name} 出售商品",
            route=route_text,
            target_city=city.sell_city_name,
            goods=goods_data,
            **profit_fields,
        )
        if not click_station(city.sell_city_name, cur_station=city_name).wait():
            emit_run_status(
                "前往卖出城市失败",
                f"未能到达 {city.sell_city_name}，正在尝试恢复",
                route=route_text,
                target_city=city.sell_city_name,
                **profit_fields,
            )
            capture_state("run_wait_sell_city_failed", extra={"target": city.sell_city_name})
            capture_page_state("run_wait_sell_city_failed", extra={"target": city.sell_city_name})
            reset_game_after_run_failure("run_wait_sell_city_failed", {"target": city.sell_city_name})
            return False
        city_name = city.sell_city_name
        emit_run_status(
            "正在打开交易所",
            f"已到达 {city_name}，正在进入卖出页面",
            route=route_text,
            current_city=city_name,
            **profit_fields,
        )
        if not go_business("sell"):
            emit_run_status(
                "打开卖出页面失败",
                f"{city_name} 交易所卖出页面打开失败，正在恢复",
                route=route_text,
                current_city=city_name,
                **profit_fields,
            )
            capture_state("run_open_sell_failed", extra={"city": city_name})
            capture_page_state("run_open_sell_failed", extra={"city": city_name})
            reset_game_after_run_failure("run_open_sell_failed", {"city": city_name})
            return False
        if not ensure_trade_strength(route_text, profit_fields):
            return False
        emit_run_status(
            "正在出售商品",
            f"正在 {city.sell_city_name} 出售本段货物",
            route=route_text,
            current_city=city.sell_city_name,
            goods=goods_data,
            **profit_fields,
        )
        if not sell_business(city.haggle_num):
            emit_run_status(
                "出售失败",
                f"{city.sell_city_name} 商品出售失败，正在尝试恢复",
                route=route_text,
                current_city=city.sell_city_name,
                **profit_fields,
            )
            capture_state("run_sell_business_failed", extra={"city": city_name})
            capture_page_state("run_sell_business_failed", extra={"city": city_name})
            reset_game_after_run_failure("run_sell_business_failed", {"city": city_name})
            return False
        # 流程跑完，更改站点名称为当前出售商品的站点
        city_name = city.sell_city_name
        emit_run_status(
            "本段跑商完成",
            f"{city.buy_city_name} -> {city.sell_city_name} 已完成",
            route=route_text,
            current_city=city.sell_city_name,
            **profit_fields,
        )
    logger.info("运行完成")
    emit_run_status("跑商完成", "全部路线执行完成", route=route_text, **profit_fields)
    return True


def two_city_run(buy_city_name: str, sell_city_name: str):
    global STOP
    STOP = False
    haggle_num = 20 if getattr(app.RunBuy, "UsePlannerHaggle", True) else int(getattr(app.RunBuy, "HaggleNum", 0) or 0)
    book_num = int(
        (getattr(app.TradePlanner, "MaxRestock", 0) if getattr(app.RunBuy, "UsePlannerBook", False) else getattr(app.RunBuy, "Book", 0))
        or 0
    )
    routes = RoutesModel(
        city_data=[
            RouteModel(
                buy_city_name=buy_city_name,
                sell_city_name=sell_city_name,
                haggle_num=haggle_num,
                book=book_num,
                goods_data=city_sell_data[buy_city_name],
            ),
            RouteModel(
                buy_city_name=sell_city_name,
                sell_city_name=buy_city_name,
                haggle_num=haggle_num,
                book=book_num,
                goods_data=city_sell_data[sell_city_name],
            ),
        ],
    )
    logger.info("准备运行跑商流程，直到体力不足、恢复失败或用户停止")
    while not STOP and not control_state.STOP:
        if not run(routes):
            break


def stop():
    """
    说明:
        停止运行
    """
    global STOP
    STOP = True
    control_state.stop()
