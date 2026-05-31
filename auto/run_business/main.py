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
from auto.module.strength import (
    MIN_TRADE_STRENGTH,
    drink_on_arrival_if_worthwhile,
    ensure_strength_available,
    reset_strength_runtime_state,
)
from auto.run_business.buy import analyze_city_trade_products, buy_business, get_boatload
from auto.run_business.config_updates import TradeRouteReplanRequired
from auto.run_business.sell import (
    HAGGLE_PERCENT_LIMIT as SELL_HAGGLE_PERCENT_LIMIT,
    sell_all_if_any,
    sell_business,
)
from auto.run_business.status_fields import routes_profit_status_fields
from core.control.control import STOP, connect, input_tap, screenshot
from core.model import app
from core.model.city_goods import RouteModel, RoutesModel
from core.module.bgr import BGR
from core.preset import click_station, get_station, go_home, go_outlets, wait_gbr
from core.preset.station import STATION
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
INITIAL_CARGO_SKIP_OCCUPIED_THRESHOLD = 10
INITIAL_CARGO_CLEAR_REMAINING_THRESHOLD = 25
ROUTE_CONTINUE_POINT = (1248, 616)
ROUTE_REVERSE_POINTS = ((1194, 639), (1172, 688))
ROUTE_RETURN_TEXTS = ("立刻返航", "立即返航")
ROUTE_RETURN_PANEL_TEXTS = ROUTE_RETURN_TEXTS + ("返航", "倒车")
ROUTE_RETURN_CONFIRM_TEXTS = ("确认", "确定")
ROUTE_RETURN_CLOSE_TEXTS = ("取消", "关闭")
ROUTE_TAKEOVER_ACTION_LABELS = {
    "continue_to_planned_destination": "继续前往规划目的地",
    "continue_without_return_panel": "未读到返航面板，继续当前行程",
    "continue_after_return_probe": "返航探测后继续当前行程",
    "return_click_failed": "返航点击失败，继续当前行程",
    "return_to_planned_city": "已立刻返航至规划城市",
}


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
    议价幅度: {route[0].haggle_num}%
    书本数量: {route[0].book}
{route[0].sell_city_name}:
    商品顺序: {"->".join(route[1].goods_data.keys())}
    议价幅度: {route[1].haggle_num}%
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


def _configured_haggle_fatigue() -> int:
    trade_planner = getattr(app, "TradePlanner", None)
    bargain = int(getattr(trade_planner, "BargainFatigue", 20) or 0)
    raise_ = int(getattr(trade_planner, "RaiseFatigue", 20) or 0)
    return max(0, bargain) + max(0, raise_)


def _leg_planned_fatigue(route: RouteModel) -> int | None:
    planned = int(getattr(route, "city_tired", 0) or 0)
    if 0 < planned < 9000 and planned != 999:
        return planned

    travel = city_fatigue_between(route.buy_city_name, route.sell_city_name)
    if travel >= 9000:
        return None
    if int(getattr(route, "haggle_num", 0) or 0) > 0:
        travel += _configured_haggle_fatigue()
    return travel


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


def _route_city_names(routes: RoutesModel) -> set[str]:
    cities: set[str] = set()
    for route in routes.city_data or []:
        if route.buy_city_name:
            cities.add(route.buy_city_name)
        if route.sell_city_name:
            cities.add(route.sell_city_name)
    return cities


def _parse_city_from_text(prefix: str, texts: list[str], route_cities: set[str]) -> str:
    for text in texts:
        clean = text.replace(" ", "")
        if prefix not in clean:
            continue
        value = clean.split(prefix, 1)[-1].lstrip(":：")
        for city in route_cities:
            if city and city in value:
                return city
        return value
    return ""


def _tap_ocr_text_any(texts: tuple[str, ...], image: Any | None = None) -> bool:
    image = image or screenshot()
    for item in image.ocr():
        item_text = item.get("text", "").replace(" ", "")
        if not any(text in item_text for text in texts):
            continue
        position = item["position"]
        center_x = int((position[0][0] + position[2][0]) / 2)
        center_y = int((position[0][1] + position[2][1]) / 2)
        input_tap((center_x, center_y))
        return True
    return False


def _route_city_in_texts(texts: list[str], route_cities: set[str]) -> str:
    clean_texts = [text.replace(" ", "") for text in texts]
    for city in sorted(route_cities, key=len, reverse=True):
        if city and any(city in text for text in clean_texts):
            return city
    return ""


def read_current_route_context(routes: RoutesModel) -> tuple[str, str, int | None, bool]:
    route_cities = _route_city_names(routes)
    image = screenshot()
    destination, remaining, cruising = STATION._read_travel_status(image)
    texts = ocr_texts(image)
    current_area = _parse_city_from_text("当前区域", texts, route_cities)
    if not destination:
        destination = _parse_city_from_text("目的地", texts, route_cities) or None
    if not current_area:
        for city in route_cities:
            if city != destination and any(city in text for text in texts):
                current_area = city
                break
    return current_area, destination or "", remaining, cruising


def _resume_phase_for_arrival(
    routes: RoutesModel,
    origin: str,
    destination: str,
) -> tuple[int, Literal["buy", "sell"]]:
    for index, route in enumerate(routes.city_data or []):
        if destination == route.sell_city_name and (not origin or origin == route.buy_city_name):
            return index, "sell"
        if destination == route.buy_city_name:
            return index, "buy"
        if destination == route.sell_city_name:
            return index, "sell"
    return 0, "buy"


def _tap_route_continue(destination: str, remaining: int | None, cruising: bool) -> bool:
    if cruising:
        return False
    logger.info(
        f"行车接管: 当前未巡航，点击右下角 D 标志继续前进 "
        f"destination={destination or '未知'} remaining={remaining if remaining is not None else '未知'}"
    )
    input_tap(ROUTE_CONTINUE_POINT)
    time.sleep(0.8)
    return True


def _open_route_return_panel(
    routes: RoutesModel,
) -> tuple[Any, list[str], str] | None:
    route_cities = _route_city_names(routes)
    attempts = (("current", None),) + tuple(
        (f"tap_reverse_{index}", point)
        for index, point in enumerate(ROUTE_REVERSE_POINTS, start=1)
    )
    last_image = None
    last_texts: list[str] = []
    for action, point in attempts:
        if point:
            input_tap(point)
            time.sleep(0.8)
        image = screenshot()
        texts = ocr_texts(image)
        clean_texts = [text.replace(" ", "") for text in texts]
        last_image = image
        last_texts = clean_texts
        if not (
            has_any_text(clean_texts, ROUTE_RETURN_PANEL_TEXTS)
            or _route_city_in_texts(clean_texts, route_cities)
        ):
            continue
        return_city = _route_city_in_texts(clean_texts, route_cities)
        logger.info(
            f"行车接管: 已打开返航面板 action={action} "
            f"return_city={return_city or '未知'} texts={clean_texts}"
        )
        return image, clean_texts, return_city
    capture_state(
        "route_return_panel_missing",
        last_image,
        extra={"texts": last_texts},
    )
    capture_page_state(
        "route_return_panel_missing",
        last_image,
        extra={"texts": last_texts},
    )
    return None


def _close_route_return_panel(image: Any | None = None) -> None:
    if _tap_ocr_text_any(ROUTE_RETURN_CLOSE_TEXTS, image):
        time.sleep(0.5)
        return
    input_tap((100, 100))
    time.sleep(0.5)


def _tap_route_immediate_return(image: Any | None = None) -> bool:
    if not _tap_ocr_text_any(ROUTE_RETURN_TEXTS, image):
        capture_state("route_immediate_return_missing")
        capture_page_state("route_immediate_return_missing")
        return False
    time.sleep(0.8)
    _tap_ocr_text_any(ROUTE_RETURN_CONFIRM_TEXTS)
    time.sleep(1.0)
    return True


def _takeover_route_direction(
    routes: RoutesModel,
    origin: str,
    destination: str,
    remaining: int | None,
    cruising: bool,
) -> tuple[str, str, int | None, bool, str]:
    route_cities = _route_city_names(routes)
    if destination in route_cities:
        _tap_route_continue(destination, remaining, cruising)
        return origin, destination, remaining, cruising, "continue_to_planned_destination"

    panel = _open_route_return_panel(routes)
    if panel is None:
        logger.warning(
            f"行车接管: 未能打开返航面板，继续前往当前目的地 "
            f"origin={origin or '未知'} destination={destination or '未知'}"
        )
        _tap_route_continue(destination, remaining, cruising)
        return origin, destination, remaining, cruising, "continue_without_return_panel"

    panel_image, _panel_texts, return_city = panel
    if not return_city and origin in route_cities:
        return_city = origin

    should_return = bool(return_city) and (
        not destination or destination not in route_cities
    )
    if not should_return:
        logger.info(
            f"行车接管: 不执行返航 origin={origin or '未知'} "
            f"destination={destination or '未知'} return_city={return_city or '未知'}"
        )
        _close_route_return_panel(panel_image)
        _tap_route_continue(destination, remaining, cruising)
        return origin, destination, remaining, cruising, "continue_after_return_probe"

    logger.info(
        f"行车接管: 当前目的地 {destination or '未知'} 不在规划内，"
        f"确认立刻返航至 {return_city}"
    )
    if not _tap_route_immediate_return(panel_image):
        _close_route_return_panel()
        _tap_route_continue(destination, remaining, cruising)
        return origin, destination, remaining, cruising, "return_click_failed"

    origin, destination, remaining, cruising = read_current_route_context(routes)
    if return_city and (not destination or destination not in route_cities):
        destination = return_city
    _tap_route_continue(destination, remaining, cruising)
    return origin, destination, remaining, cruising, "return_to_planned_city"


def handle_initial_route_state(
    routes: RoutesModel,
    route_text: str,
    profit_fields: dict[str, Any],
) -> tuple[str, int, Literal["buy", "sell"]] | None:
    state = classify_page()
    if state.kind not in (PageKind.ROUTE, PageKind.ROUTE_EVENT, PageKind.FIGHT, PageKind.FIGHT_END):
        return None

    origin, destination, remaining, cruising = read_current_route_context(routes)
    origin, destination, remaining, cruising, takeover_action = _takeover_route_direction(
        routes,
        origin,
        destination,
        remaining,
        cruising,
    )

    emit_run_status(
        "检测到行车途中",
        (
            f"当前正在前往 {destination or '未知目的地'}"
            + (f"，剩余 {remaining}km" if remaining is not None else "")
            + f"，{ROUTE_TAKEOVER_ACTION_LABELS.get(takeover_action, takeover_action)}"
        ),
        route=route_text,
        current_city=origin,
        target_city=destination,
        **profit_fields,
    )
    if not STATION(True).wait():
        capture_state(
            "run_initial_route_wait_failed",
            extra={"origin": origin, "destination": destination},
        )
        capture_page_state(
            "run_initial_route_wait_failed",
            extra={"origin": origin, "destination": destination},
        )
        return None

    route_cities = _route_city_names(routes)
    if not destination or destination not in route_cities:
        try:
            destination = get_station(is_go_home=False)
        except Exception as exc:
            logger.warning(f"行车接管完成后识别城市失败: {exc}")
            destination = ""
    index, phase = _resume_phase_for_arrival(routes, origin, destination)
    logger.info(
        f"行车途中接管完成: origin={origin or '未知'} destination={destination or '未知'} "
        f"resume_index={index} phase={phase}"
    )
    return destination, index, phase


def clear_initial_cargo_if_needed(
    city_name: str,
    route_text: str,
    profit_fields: dict[str, Any],
) -> bool:
    remaining = get_boatload()
    occupied = max(0, 100 - remaining)
    if occupied < INITIAL_CARGO_SKIP_OCCUPIED_THRESHOLD:
        emit_run_status(
            "跳过清空货柜",
            f"货柜内遗留物品约 {occupied}%，少于 10%，继续买入流程",
            route=route_text,
            current_city=city_name,
            **profit_fields,
        )
        logger.info(f"首次进买入页检测到货柜遗留物品较少: 占用约 {occupied}%，跳过清空货柜")
        return True
    very_full = remaining <= INITIAL_CARGO_CLEAR_REMAINING_THRESHOLD
    emit_run_status(
        "正在检查货柜",
        (
            f"剩余货舱约 {remaining}%，货柜占用约 {occupied}%，遗留货物将抬价到满"
            if very_full
            else f"剩余货舱约 {remaining}%，货柜占用约 {occupied}%，正在清空遗留货物"
        ),
        route=route_text,
        current_city=city_name,
        **profit_fields,
    )
    if not go_business("sell"):
        return False
    raise_percent = SELL_HAGGLE_PERCENT_LIMIT if very_full else 0
    if very_full:
        logger.info(
            f"首次进买入页检测到货仓很满: 剩余货舱约 {remaining}%，"
            f"清仓卖出将抬价到 {raise_percent}%"
        )
    if not sell_all_if_any(raise_percent, empty_ok=True):
        return False
    if not go_business("buy"):
        return False
    return True


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
        logger.info(f"当前在相反交易页，直接切换到 {'买入' if type == 'buy' else '卖出'} 页面")
        if click_business_menu_option(type):
            return True
        input_tap((103, 654))
        time.sleep(1.0)
        if is_business_page(type):
            return True
        state = classify_page()
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


def ensure_trade_strength(
    route_text: str,
    profit_fields: dict[str, Any],
    required_fatigue: int = MIN_TRADE_STRENGTH,
    context: str = "交易操作",
) -> bool:
    return ensure_strength_available(
        required_fatigue,
        context=context,
        route=route_text,
        status_fields=profit_fields,
    )


def ensure_business_page_ready(
    type: Literal["buy", "sell"],
    city_name: str,
    route_text: str,
    profit_fields: dict[str, Any],
    context: str,
) -> bool:
    target_page = PageKind.BUY_PAGE if type == "buy" else PageKind.SELL_PAGE
    state = classify_page()
    if state.kind == target_page or is_business_page(type):
        return True
    logger.warning(
        f"{context}后不在目标交易页: expected={target_page.value} "
        f"actual={state.kind.value} confidence={state.confidence}"
    )
    emit_run_status(
        "正在恢复交易页",
        f"{context}后正在重新进入{'买入' if type == 'buy' else '卖出'}页面",
        route=route_text,
        current_city=city_name,
        **profit_fields,
    )
    if go_business(type):
        return True
    capture_state(
        f"run_restore_{type}_page_failed",
        extra={"city": city_name, "context": context, "actual": state.kind.value},
    )
    capture_page_state(
        f"run_restore_{type}_page_failed",
        extra={"city": city_name, "context": context, "actual": state.kind.value},
    )
    return False


def drink_after_arrival_if_needed(city_name: str, route_text: str, profit_fields: dict[str, Any]) -> None:
    emit_run_status(
        "检查喝酒恢复",
        f"已到达 {city_name}，正在检查是否需要优先喝酒",
        route=route_text,
        current_city=city_name,
        **profit_fields,
    )
    if drink_on_arrival_if_worthwhile(city_name):
        emit_run_status(
            "喝酒完成",
            f"{city_name} 已尝试喝酒恢复疲劳",
            route=route_text,
            current_city=city_name,
            **profit_fields,
        )


def run(routes: RoutesModel, start_city_name: str | None = None):
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
    emit_run_status(
        "连接成功",
        "已连接游戏，正在识别当前页面",
        route=route_text,
        **profit_fields,
    )
    resume = handle_initial_route_state(routes, route_text, profit_fields)
    start_index = 0
    start_phase: Literal["buy", "sell"] = "buy"
    if resume:
        city_name, start_index, start_phase = resume
        phase_text = "买入" if start_phase == "buy" else "卖出"
        emit_run_status(
            "已接管当前行程",
            f"已到达 {city_name}，将从第 {start_index + 1} 段{phase_text}继续",
            route=route_text,
            current_city=city_name,
            **profit_fields,
        )
    elif start_city_name:
        city_name = start_city_name
        if reorder_route_by_current_city(routes, city_name):
            route_text = _routes_text(routes)
            profit_fields = routes_profit_status_fields(routes)
        emit_run_status(
            "已确认当前位置",
            f"当前城市：{city_name}，准备开始跑商",
            route=route_text,
            current_city=city_name,
            **profit_fields,
        )
    else:
        city_name = get_station(is_go_home=False)
        if reorder_route_by_current_city(routes, city_name):
            route_text = _routes_text(routes)
            profit_fields = routes_profit_status_fields(routes)
        emit_run_status(
            "已确认当前位置",
            f"当前城市：{city_name}，准备开始跑商",
            route=route_text,
            current_city=city_name,
            **profit_fields,
        )
    initial_cargo_checked = start_phase == "sell"
    for route_index, city in enumerate(routes.city_data):
        if route_index < start_index:
            continue
        phase: Literal["buy", "sell"] = start_phase if route_index == start_index else "buy"
        logger.info(f"{city.buy_city_name}->{city.sell_city_name}")
        goods_data = list(city.goods_data.keys())
        if phase == "buy":
            already_at_buy_city = city_name == city.buy_city_name
            emit_run_status(
                "正在前往买入城市",
                f"已在 {city.buy_city_name}，准备购买商品" if already_at_buy_city else f"准备在 {city.buy_city_name} 购买商品",
                route=route_text,
                current_city=city_name if already_at_buy_city else "",
                target_city=city.buy_city_name,
                goods=goods_data,
                **profit_fields,
            )
            if not already_at_buy_city and not click_station(city.buy_city_name, cur_station=city_name).wait():
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
            if not already_at_buy_city:
                logger.info(f"已到达 {city_name}，喝酒检查延后到交易所页面执行")
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
            if not already_at_buy_city:
                drink_after_arrival_if_needed(city_name, route_text, profit_fields)
                if not ensure_business_page_ready(
                    "buy",
                    city_name,
                    route_text,
                    profit_fields,
                    "到站喝酒检查",
                ):
                    emit_run_status(
                        "恢复买入页面失败",
                        f"{city_name} 到站喝酒检查后未能回到买入页面",
                        route=route_text,
                        current_city=city_name,
                        **profit_fields,
                    )
                    reset_game_after_run_failure("run_restore_buy_after_drink_failed", {"city": city_name})
                    return False
            if not initial_cargo_checked:
                if not clear_initial_cargo_if_needed(city_name, route_text, profit_fields):
                    emit_run_status(
                        "清空货柜失败",
                        f"{city_name} 遗留货物清空失败，跑商已停止",
                        route=route_text,
                        current_city=city_name,
                        **profit_fields,
                    )
                    capture_state("run_clear_initial_cargo_failed", extra={"city": city_name})
                    capture_page_state("run_clear_initial_cargo_failed", extra={"city": city_name})
                    reset_game_after_run_failure("run_clear_initial_cargo_failed", {"city": city_name})
                    return False
                initial_cargo_checked = True
            if analyze_city_trade_products(city.buy_city_name):
                raise TradeRouteReplanRequired(f"{city.buy_city_name} 商品解锁状态变化")
            leg_fatigue = _leg_planned_fatigue(city) or MIN_TRADE_STRENGTH
            if not ensure_trade_strength(
                route_text,
                profit_fields,
                required_fatigue=leg_fatigue,
                context=f"{city.buy_city_name} -> {city.sell_city_name} 本段跑商",
            ):
                return False
            if not ensure_business_page_ready(
                "buy",
                city_name,
                route_text,
                profit_fields,
                "疲劳检查",
            ):
                emit_run_status(
                    "恢复买入页面失败",
                    f"{city_name} 疲劳检查后未能回到买入页面",
                    route=route_text,
                    current_city=city_name,
                    **profit_fields,
                )
                reset_game_after_run_failure("run_restore_buy_after_strength_failed", {"city": city_name})
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
        logger.info(f"已到达 {city_name}，喝酒检查延后到交易所页面执行")
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
        drink_after_arrival_if_needed(city_name, route_text, profit_fields)
        if not ensure_business_page_ready(
            "sell",
            city_name,
            route_text,
            profit_fields,
            "到站喝酒检查",
        ):
            emit_run_status(
                "恢复卖出页面失败",
                f"{city_name} 到站喝酒检查后未能回到卖出页面",
                route=route_text,
                current_city=city_name,
                **profit_fields,
            )
            reset_game_after_run_failure("run_restore_sell_after_drink_failed", {"city": city_name})
            return False
        if not ensure_trade_strength(route_text, profit_fields):
            return False
        if not ensure_business_page_ready(
            "sell",
            city_name,
            route_text,
            profit_fields,
            "疲劳检查",
        ):
            emit_run_status(
                "恢复卖出页面失败",
                f"{city_name} 疲劳检查后未能回到卖出页面",
                route=route_text,
                current_city=city_name,
                **profit_fields,
            )
            reset_game_after_run_failure("run_restore_sell_after_strength_failed", {"city": city_name})
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
    reset_strength_runtime_state()
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
    for route in routes.city_data:
        fatigue = _leg_planned_fatigue(route)
        if fatigue is not None:
            route.city_tired = fatigue
    routes.city_tired = sum(
        int(route.city_tired or 0)
        for route in routes.city_data
        if 0 < int(route.city_tired or 0) < 9000 and int(route.city_tired or 0) != 999
    )
    logger.info("准备运行跑商流程，直到体力不足、恢复失败或用户停止")
    known_city_name: str | None = None
    while not STOP and not control_state.STOP:
        if not run(routes, start_city_name=known_city_name):
            break
        if routes.city_data:
            known_city_name = routes.city_data[-1].sell_city_name


def stop():
    """
    说明:
        停止运行
    """
    global STOP
    STOP = True
    control_state.stop()
