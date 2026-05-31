from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from loguru import logger

from app.common.account_config import account_config_auto_enabled
from app.common.config import cfg
from app.common.runtime_status import emit_run_status
import core.control.control as control_state
from auto.run_business.config_updates import TradeRouteReplanRequired, update_trade_account_profile
from auto.run_business.main import run
from auto.module.strength import reset_strength_runtime_state
from auto.run_business.planner import (
    DEFAULT_MARKET_CACHE_TTL,
    MarketData,
    MixedCurrencyPriority,
    RoutePlanOptions,
    RouteStrategy,
    load_market_data,
    load_market_data_file,
    normalize_city_pairs,
    normalize_mixed_currency_priority,
    plan_two_city_routes,
    summarize_routes,
)
from auto.run_business.status_fields import summary_profit_status_fields
from auto.run_business.planner_config import load_trade_planner_config, route_plan_options_from_config
from core.model import app
from core.model.city_goods import RoutesModel
from core.preset import go_home


MAX_RUNTIME_REPLAN_ATTEMPTS = 3


def _city_set(values: list[str] | tuple[str, ...] | set[str] | None) -> set[str] | None:
    result = {str(value).strip() for value in values or [] if str(value).strip()}
    return result or None


def _bool_value(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "已解锁", "解锁", "开启"}
    return bool(value)


def _split_city_good_key(key: str) -> tuple[str | None, str]:
    text = str(key).strip()
    for delimiter in ("/", "\\", "|"):
        if delimiter in text:
            city, good = [part.strip() for part in text.split(delimiter, 1)]
            if city and good:
                return city, good
    return None, text


def _split_product_unlock_status(
    values: dict[str, object] | None,
) -> tuple[dict[str, bool], dict[str, dict[str, bool]]]:
    global_status: dict[str, bool] = {}
    city_status: dict[str, dict[str, bool]] = {}
    for raw_key, raw_value in (values or {}).items():
        city, good = _split_city_good_key(str(raw_key))
        if not good:
            continue
        value = _bool_value(raw_value)
        if city:
            city_status.setdefault(city, {})[good] = value
        else:
            global_status[good] = value
    return global_status, city_status


def _merge_product_unlock_status_by_city(
    base: dict[str, dict[str, bool]] | None,
    updates: dict[str, dict[str, bool]] | None,
) -> dict[str, dict[str, bool]]:
    merged: dict[str, dict[str, bool]] = {
        str(city): {str(good): _bool_value(unlocked) for good, unlocked in goods.items()}
        for city, goods in (base or {}).items()
        if isinstance(goods, dict)
    }
    for city, goods in (updates or {}).items():
        if not isinstance(goods, dict):
            continue
        city_status = dict(merged.get(str(city)) or {})
        city_status.update({str(good): _bool_value(unlocked) for good, unlocked in goods.items()})
        merged[str(city)] = city_status
    return merged


def _role_resonance(values: dict[str, object] | None) -> dict[str, dict[str, int]]:
    roles: dict[str, dict[str, int]] = {}
    for role_name, value in (values or {}).items():
        if isinstance(value, dict):
            resonance = int(value.get("resonance") or 0)
        else:
            resonance = int(value or 0)
        if resonance <= 0:
            resonance = 0
        elif resonance < 4:
            resonance = 1
        elif resonance > 5:
            resonance = 5
        roles[role_name] = {"resonance": resonance}
    return roles


def _configured_unavailable_cities() -> set[str]:
    return {
        str(city).strip()
        for city in (cfg.tradePlannerUnavailableCities.value or [])
        if str(city).strip()
    }


def refresh_unavailable_cities_before_planning(
    exclude_cities: set[str] | None,
) -> set[str] | None:
    """Refresh account-derived locked cities before route planning."""
    if not account_config_auto_enabled():
        return exclude_cities

    old_unavailable = _configured_unavailable_cities()
    if not old_unavailable:
        return exclude_cities

    emit_run_status(
        "正在检查未解锁城市",
        f"正在复查 {len(old_unavailable)} 个账号配置未解锁城市",
    )
    if not control_state.connect():
        logger.warning("检查未解锁城市前连接游戏失败，沿用现有未解锁城市配置")
        return exclude_cities

    try:
        from auto.run_business.account_profile import read_unavailable_map_cities

        still_unavailable = read_unavailable_map_cities(sorted(old_unavailable))
    except Exception as exc:
        logger.exception(f"启动脚本检查未解锁城市失败: {exc}")
        emit_run_status("未解锁城市检查失败", "沿用现有未解锁城市配置")
        return exclude_cities

    if still_unavailable is None:
        logger.warning("检查未解锁城市未得到结果，沿用现有未解锁城市配置")
        return exclude_cities

    still_unavailable_set = {
        str(city).strip() for city in still_unavailable if str(city).strip()
    }
    unlocked_cities = sorted(old_unavailable - still_unavailable_set)
    update_trade_account_profile(
        unavailable_cities=sorted(still_unavailable_set),
        reason="启动脚本检查城市开放状态",
    )
    if unlocked_cities:
        emit_run_status(
            "未解锁城市已更新",
            "已解锁：" + "、".join(unlocked_cities),
        )

    if exclude_cities is None:
        return None

    user_excluded = _city_set(getattr(app.TradePlanner, "ExcludeCities", [])) or set()
    return (set(exclude_cities) - old_unavailable) | still_unavailable_set | user_excluded


@dataclass
class PlannedBusinessResult:
    ok: bool
    executed: bool
    route: RoutesModel | None
    summary: dict[str, Any] | None
    error: str | None = None


def _summary_route_text(summary: dict[str, Any] | None) -> str:
    legs = (summary or {}).get("legs") or []
    if not legs:
        return ""
    buy_city = str(legs[0].get("buy_city") or "")
    sell_city = str(legs[0].get("sell_city") or "")
    if buy_city and sell_city:
        return f"{buy_city} <-> {sell_city}"
    return buy_city or sell_city


def app_route_plan_options(
    market: MarketData,
    *,
    strategy: RouteStrategy = "general_profit_index",
    mixed_currency_priority: MixedCurrencyPriority | None = None,
    max_goods_num: int | None = None,
    max_restock: int | None = None,
    max_book_by_city: dict[str, int] | None = None,
    haggle_by_city: dict[str, int] | None = None,
    auto_haggle: bool | None = None,
    planner_config: str | None = None,
    include_cities: set[str] | None = None,
    exclude_cities: set[str] | None = None,
    directed_city_pairs: set[tuple[str, str]] | None = None,
    allowed_city_pairs: set[frozenset[str]] | None = None,
    blocked_city_pairs: set[frozenset[str]] | None = None,
    allowed_goods: set[str] | None = None,
    blocked_goods: set[str] | None = None,
    default_prestige_level: int | None = None,
    prestige_by_city: dict[str, int] | None = None,
    roles: dict[str, dict[str, int]] | None = None,
    use_default_roles: bool | None = None,
    disabled_roles: set[str] | None = None,
    product_unlock_status: dict[str, bool] | None = None,
    product_unlock_status_by_city: dict[str, dict[str, bool]] | None = None,
    use_default_product_unlock_status: bool | None = None,
    min_profit: int = 1,
) -> RoutePlanOptions:
    trade_planner = getattr(app, "TradePlanner", None)
    run_buy = getattr(app, "RunBuy", None)
    cities = set(market.sell_prices.keys())
    use_planner_book = bool(getattr(run_buy, "UsePlannerBook", True))
    use_planner_haggle = bool(getattr(run_buy, "UsePlannerHaggle", True))
    global_book = int(getattr(run_buy, "Book", 0) or 0)
    outbound_book = int(getattr(run_buy, "OutboundBook", global_book) or 0)
    return_book = int(getattr(run_buy, "ReturnBook", global_book) or 0)
    selection_mode = str(getattr(trade_planner, "CitySelectionMode", "") or "")
    manual_start = str(getattr(trade_planner, "ManualStartCity", "") or "")
    manual_target = str(getattr(trade_planner, "ManualTargetCity", "") or "")
    if not use_planner_book and selection_mode == "manual" and manual_start and manual_target:
        city_books = {
            manual_start: outbound_book,
            manual_target: return_book,
        }
    else:
        city_books = {} if use_planner_book else {city: global_book for city in cities}
    config_max_restock = int(getattr(trade_planner, "MaxRestock", 6) or 6)
    config_max_lot = int(getattr(trade_planner, "MaxLot", 1136) or 1136)
    if max_restock is not None:
        resolved_max_restock = max_restock
    elif use_planner_book:
        resolved_max_restock = config_max_restock
    else:
        resolved_max_restock = outbound_book + return_book
    if resolved_max_restock is None:
        resolved_max_restock = max(city_books.values(), default=0) or 4
    resolved_max_goods_num = max_goods_num if max_goods_num is not None else config_max_lot
    global_haggle = int(getattr(run_buy, "HaggleNum", 0) or 0)
    if not use_planner_haggle and selection_mode == "manual" and manual_start and manual_target:
        city_haggles = {
            manual_start: int(getattr(run_buy, "OutboundHaggleNum", global_haggle) or 0),
            manual_target: int(getattr(run_buy, "ReturnHaggleNum", global_haggle) or 0),
        }
    else:
        city_haggles = {city: global_haggle for city in cities}
    configured_unlock_status, configured_unlock_status_by_city = _split_product_unlock_status(
        dict(getattr(trade_planner, "ProductUnlockStatus", {}) or {})
    )
    configured_unlock_status_by_city.update(
        {
            str(city): {str(good): _bool_value(unlocked) for good, unlocked in goods.items()}
            for city, goods in dict(getattr(trade_planner, "ProductUnlockStatusByCity", {}) or {}).items()
            if isinstance(goods, dict)
        }
    )
    configured_exclude_cities = (
        (_city_set(getattr(trade_planner, "ExcludeCities", [])) or set())
        | _configured_unavailable_cities()
    )
    options = RoutePlanOptions(
        strategy=strategy,
        mixed_currency_priority=normalize_mixed_currency_priority(
            mixed_currency_priority
            or getattr(trade_planner, "MixedCurrencyPriority", "total")
        ),
        max_goods_num=resolved_max_goods_num,
        max_restock=int(resolved_max_restock),
        max_book_by_city=city_books,
        haggle_by_city=city_haggles,
        auto_haggle=use_planner_haggle,
        include_cities=_city_set(getattr(trade_planner, "IncludeCities", [])),
        exclude_cities=configured_exclude_cities or None,
        directed_city_pairs=None,
        allowed_city_pairs=normalize_city_pairs(getattr(trade_planner, "AllowedCityPairs", [])),
        blocked_city_pairs=normalize_city_pairs(getattr(trade_planner, "BlockedCityPairs", [])),
        allowed_goods=_city_set(getattr(trade_planner, "AllowedGoods", [])),
        blocked_goods=_city_set(getattr(trade_planner, "BlockedGoods", [])),
        min_profit=min_profit,
        bargain_percent=int(getattr(trade_planner, "BargainPercent", 20) or 0),
        raise_percent=int(getattr(trade_planner, "RaisePercent", 20) or 0),
        bargain_fatigue=int(getattr(trade_planner, "BargainFatigue", 20) or 0),
        raise_fatigue=int(getattr(trade_planner, "RaiseFatigue", 20) or 0),
        compare_no_return_bargain=bool(getattr(trade_planner, "CompareNoReturnBargain", True)),
        default_prestige_level=int(getattr(trade_planner, "DefaultPrestigeLevel", 20) or 20),
        prestige_by_city=dict(getattr(trade_planner, "PrestigeByCity", {}) or {}),
        roles=_role_resonance(roles if roles is not None else getattr(trade_planner, "RoleResonance", {})),
        use_default_roles=bool(use_default_roles) if use_default_roles is not None else True,
        disabled_roles=disabled_roles if disabled_roles is not None else None,
        product_unlock_status=configured_unlock_status,
        product_unlock_status_by_city=configured_unlock_status_by_city,
        use_default_product_unlock_status=False,
        events=dict(getattr(trade_planner, "Events", {}) or {}),
    )
    config_path = planner_config or getattr(trade_planner, "ConfigPath", "") or None
    options = route_plan_options_from_config(load_trade_planner_config(config_path), options)

    overrides: dict[str, Any] = {}
    if max_goods_num is not None:
        overrides["max_goods_num"] = max_goods_num
    if max_restock is not None:
        overrides["max_restock"] = max_restock
    if max_book_by_city is not None:
        overrides["max_book_by_city"] = {
            str(city): int(book) for city, book in max_book_by_city.items()
        }
    if haggle_by_city is not None:
        overrides["haggle_by_city"] = {
            str(city): int(haggle) for city, haggle in haggle_by_city.items()
        }
    if auto_haggle is not None:
        overrides["auto_haggle"] = bool(auto_haggle)
    if mixed_currency_priority is not None:
        overrides["mixed_currency_priority"] = normalize_mixed_currency_priority(
            mixed_currency_priority
        )
    if include_cities is not None:
        overrides["include_cities"] = include_cities
    if exclude_cities is not None:
        overrides["exclude_cities"] = exclude_cities
    if directed_city_pairs is not None:
        overrides["directed_city_pairs"] = directed_city_pairs
    if allowed_city_pairs is not None:
        overrides["allowed_city_pairs"] = allowed_city_pairs
    if blocked_city_pairs is not None:
        overrides["blocked_city_pairs"] = blocked_city_pairs
    if allowed_goods is not None:
        overrides["allowed_goods"] = allowed_goods
    if blocked_goods is not None:
        overrides["blocked_goods"] = blocked_goods
    if default_prestige_level is not None:
        overrides["default_prestige_level"] = int(default_prestige_level)
    if prestige_by_city is not None:
        overrides["prestige_by_city"] = {
            str(city): int(level) for city, level in prestige_by_city.items()
        }
    if roles is not None:
        overrides["roles"] = _role_resonance(roles)
    if use_default_roles is not None:
        overrides["use_default_roles"] = bool(use_default_roles)
    if disabled_roles is not None:
        overrides["disabled_roles"] = {str(role) for role in disabled_roles if str(role).strip()}
    if product_unlock_status is not None:
        unlock_status, unlock_status_by_city = _split_product_unlock_status(product_unlock_status)
        overrides["product_unlock_status"] = unlock_status
        if unlock_status_by_city:
            overrides["product_unlock_status_by_city"] = _merge_product_unlock_status_by_city(
                options.product_unlock_status_by_city,
                unlock_status_by_city,
            )
    if product_unlock_status_by_city is not None:
        merged_status = _merge_product_unlock_status_by_city(
            overrides.get("product_unlock_status_by_city")
            or options.product_unlock_status_by_city,
            product_unlock_status_by_city,
        )
        if merged_status:
            overrides["product_unlock_status_by_city"] = merged_status
    if use_default_product_unlock_status is not None:
        overrides["use_default_product_unlock_status"] = bool(use_default_product_unlock_status)
    return replace(options, **overrides) if overrides else options


def load_planner_market(
    *,
    api_url: str | None = None,
    api_file: str | None = None,
    cache_ttl: float | None = DEFAULT_MARKET_CACHE_TTL,
    use_cache: bool = True,
    refresh_cache: bool = False,
    use_local_baseline: bool = False,
) -> MarketData:
    if api_file:
        return load_market_data_file(api_file)
    if api_url is None:
        trade_planner = getattr(app, "TradePlanner", None)
        api_url = getattr(trade_planner, "ApiUrl", "") or None
    return load_market_data(
        api_url,
        cache_ttl=cache_ttl,
        use_cache=use_cache,
        refresh_cache=refresh_cache,
        use_local_baseline=use_local_baseline,
    )


def select_planned_routes(
    *,
    api_url: str | None = None,
    api_file: str | None = None,
    strategy: RouteStrategy = "general_profit_index",
    mixed_currency_priority: MixedCurrencyPriority | None = None,
    top_n: int = 3,
    max_goods_num: int | None = None,
    max_restock: int | None = None,
    max_book_by_city: dict[str, int] | None = None,
    haggle_by_city: dict[str, int] | None = None,
    auto_haggle: bool | None = None,
    planner_config: str | None = None,
    include_cities: set[str] | None = None,
    exclude_cities: set[str] | None = None,
    directed_city_pairs: set[tuple[str, str]] | None = None,
    allowed_city_pairs: set[frozenset[str]] | None = None,
    blocked_city_pairs: set[frozenset[str]] | None = None,
    allowed_goods: set[str] | None = None,
    blocked_goods: set[str] | None = None,
    default_prestige_level: int | None = None,
    prestige_by_city: dict[str, int] | None = None,
    roles: dict[str, dict[str, int]] | None = None,
    use_default_roles: bool | None = None,
    disabled_roles: set[str] | None = None,
    product_unlock_status: dict[str, bool] | None = None,
    product_unlock_status_by_city: dict[str, dict[str, bool]] | None = None,
    use_default_product_unlock_status: bool | None = None,
    min_profit: int = 1,
    cache_ttl: float | None = DEFAULT_MARKET_CACHE_TTL,
    use_cache: bool = True,
    refresh_cache: bool = False,
    use_local_baseline: bool = False,
) -> tuple[list[tuple[RoutesModel, dict[str, Any]]], str | None]:
    exclude_cities = refresh_unavailable_cities_before_planning(exclude_cities)
    emit_run_status("正在规划路线", "正在读取行情并计算推荐路线")
    market = load_planner_market(
        api_url=api_url,
        api_file=api_file,
        cache_ttl=cache_ttl,
        use_cache=use_cache,
        refresh_cache=refresh_cache,
        use_local_baseline=use_local_baseline,
    )
    options = app_route_plan_options(
        market,
        strategy=strategy,
        mixed_currency_priority=mixed_currency_priority,
        max_goods_num=max_goods_num,
        max_restock=max_restock,
        max_book_by_city=max_book_by_city,
        haggle_by_city=haggle_by_city,
        auto_haggle=auto_haggle,
        planner_config=planner_config,
        include_cities=include_cities,
        exclude_cities=exclude_cities,
        directed_city_pairs=directed_city_pairs,
        allowed_city_pairs=allowed_city_pairs,
        blocked_city_pairs=blocked_city_pairs,
        allowed_goods=allowed_goods,
        blocked_goods=blocked_goods,
        default_prestige_level=default_prestige_level,
        prestige_by_city=prestige_by_city,
        roles=roles,
        use_default_roles=use_default_roles,
        disabled_roles=disabled_roles,
        product_unlock_status=product_unlock_status,
        product_unlock_status_by_city=product_unlock_status_by_city,
        use_default_product_unlock_status=use_default_product_unlock_status,
        min_profit=min_profit,
    )
    routes = plan_two_city_routes(market, options)
    if not routes:
        emit_run_status("规划失败", "没有计算出可跑的双城路线")
        return [], "没有计算出可跑的双城路线"

    candidates = [
        (route, summarize_routes(route, strategy))
        for route in routes[: max(1, int(top_n or 1))]
    ]
    first_summary = candidates[0][1]
    emit_run_status(
        "规划完成",
        f"已计算出 {len(candidates)} 条候选路线",
        route=_summary_route_text(first_summary),
        **summary_profit_status_fields(first_summary),
    )
    return candidates, None


def select_planned_route(
    *,
    api_url: str | None = None,
    api_file: str | None = None,
    strategy: RouteStrategy = "general_profit_index",
    mixed_currency_priority: MixedCurrencyPriority | None = None,
    route_index: int = 0,
    max_goods_num: int | None = None,
    max_restock: int | None = None,
    max_book_by_city: dict[str, int] | None = None,
    haggle_by_city: dict[str, int] | None = None,
    auto_haggle: bool | None = None,
    planner_config: str | None = None,
    include_cities: set[str] | None = None,
    exclude_cities: set[str] | None = None,
    directed_city_pairs: set[tuple[str, str]] | None = None,
    allowed_city_pairs: set[frozenset[str]] | None = None,
    blocked_city_pairs: set[frozenset[str]] | None = None,
    allowed_goods: set[str] | None = None,
    blocked_goods: set[str] | None = None,
    default_prestige_level: int | None = None,
    prestige_by_city: dict[str, int] | None = None,
    roles: dict[str, dict[str, int]] | None = None,
    use_default_roles: bool | None = None,
    disabled_roles: set[str] | None = None,
    product_unlock_status: dict[str, bool] | None = None,
    product_unlock_status_by_city: dict[str, dict[str, bool]] | None = None,
    use_default_product_unlock_status: bool | None = None,
    min_profit: int = 1,
    cache_ttl: float | None = DEFAULT_MARKET_CACHE_TTL,
    use_cache: bool = True,
    refresh_cache: bool = False,
    use_local_baseline: bool = False,
) -> tuple[RoutesModel | None, dict[str, Any] | None, str | None]:
    candidates, error = select_planned_routes(
        api_url=api_url,
        api_file=api_file,
        strategy=strategy,
        mixed_currency_priority=mixed_currency_priority,
        top_n=max(1, int(route_index or 0) + 1),
        max_goods_num=max_goods_num,
        max_restock=max_restock,
        max_book_by_city=max_book_by_city,
        haggle_by_city=haggle_by_city,
        auto_haggle=auto_haggle,
        planner_config=planner_config,
        include_cities=include_cities,
        exclude_cities=exclude_cities,
        directed_city_pairs=directed_city_pairs,
        allowed_city_pairs=allowed_city_pairs,
        blocked_city_pairs=blocked_city_pairs,
        allowed_goods=allowed_goods,
        blocked_goods=blocked_goods,
        default_prestige_level=default_prestige_level,
        prestige_by_city=prestige_by_city,
        roles=roles,
        use_default_roles=use_default_roles,
        disabled_roles=disabled_roles,
        product_unlock_status=product_unlock_status,
        product_unlock_status_by_city=product_unlock_status_by_city,
        use_default_product_unlock_status=use_default_product_unlock_status,
        min_profit=min_profit,
        cache_ttl=cache_ttl,
        use_cache=use_cache,
        refresh_cache=refresh_cache,
        use_local_baseline=use_local_baseline,
    )
    if error or not candidates:
        return None, None, error or "没有计算出可跑的双城路线"

    index = min(max(route_index, 0), len(candidates) - 1)
    route, summary = candidates[index]
    return route, summary, None


def run_planned_business(
    *,
    api_url: str | None = None,
    api_file: str | None = None,
    strategy: RouteStrategy = "general_profit_index",
    mixed_currency_priority: MixedCurrencyPriority | None = None,
    route_index: int = 0,
    max_goods_num: int | None = None,
    max_restock: int | None = None,
    max_book_by_city: dict[str, int] | None = None,
    haggle_by_city: dict[str, int] | None = None,
    auto_haggle: bool | None = None,
    planner_config: str | None = None,
    include_cities: set[str] | None = None,
    exclude_cities: set[str] | None = None,
    directed_city_pairs: set[tuple[str, str]] | None = None,
    allowed_city_pairs: set[frozenset[str]] | None = None,
    blocked_city_pairs: set[frozenset[str]] | None = None,
    allowed_goods: set[str] | None = None,
    blocked_goods: set[str] | None = None,
    default_prestige_level: int | None = None,
    prestige_by_city: dict[str, int] | None = None,
    roles: dict[str, dict[str, int]] | None = None,
    use_default_roles: bool | None = None,
    disabled_roles: set[str] | None = None,
    product_unlock_status: dict[str, bool] | None = None,
    product_unlock_status_by_city: dict[str, dict[str, bool]] | None = None,
    use_default_product_unlock_status: bool | None = None,
    min_profit: int = 1,
    cache_ttl: float | None = DEFAULT_MARKET_CACHE_TTL,
    use_cache: bool = True,
    refresh_cache: bool = False,
    use_local_baseline: bool = False,
    execute: bool = False,
) -> PlannedBusinessResult:
    route, summary, error = select_planned_route(
        api_url=api_url,
        api_file=api_file,
        strategy=strategy,
        mixed_currency_priority=mixed_currency_priority,
        route_index=route_index,
        max_goods_num=max_goods_num,
        max_restock=max_restock,
        max_book_by_city=max_book_by_city,
        haggle_by_city=haggle_by_city,
        auto_haggle=auto_haggle,
        planner_config=planner_config,
        include_cities=include_cities,
        exclude_cities=exclude_cities,
        directed_city_pairs=directed_city_pairs,
        allowed_city_pairs=allowed_city_pairs,
        blocked_city_pairs=blocked_city_pairs,
        allowed_goods=allowed_goods,
        blocked_goods=blocked_goods,
        default_prestige_level=default_prestige_level,
        prestige_by_city=prestige_by_city,
        roles=roles,
        use_default_roles=use_default_roles,
        disabled_roles=disabled_roles,
        product_unlock_status=product_unlock_status,
        product_unlock_status_by_city=product_unlock_status_by_city,
        use_default_product_unlock_status=use_default_product_unlock_status,
        min_profit=min_profit,
        cache_ttl=cache_ttl,
        use_cache=use_cache,
        refresh_cache=refresh_cache,
        use_local_baseline=use_local_baseline,
    )
    if not route:
        logger.warning(error)
        emit_run_status("跑商失败", error or "自动规划跑商失败")
        return PlannedBusinessResult(False, False, None, None, error)
    if not execute:
        return PlannedBusinessResult(True, False, route, summary)

    return execute_planned_route(route=route, summary=summary, strategy=strategy)


def execute_planned_route(
    *,
    route: RoutesModel,
    summary: dict[str, Any] | None = None,
    strategy: RouteStrategy = "general_profit_index",
) -> PlannedBusinessResult:
    summary = summary or summarize_routes(route, strategy)
    logger.info(f"开始执行自动规划跑商路线: {summary}")
    emit_run_status(
        "开始执行跑商",
        "正在按自动规划路线运行",
        route=_summary_route_text(summary),
        **summary_profit_status_fields(summary),
    )
    control_state.STOP = False
    reset_strength_runtime_state()
    ok = False
    replan_attempts = 0
    while not control_state.STOP:
        try:
            ok = bool(run(route))
        except TradeRouteReplanRequired as exc:
            replan_attempts += 1
            if replan_attempts > MAX_RUNTIME_REPLAN_ATTEMPTS:
                error = "商品解锁状态反复变化，已达到重新规划上限"
                logger.warning(f"{error}: {exc}")
                emit_run_status("重新规划失败", error)
                return PlannedBusinessResult(False, True, route, summary, error)

            logger.warning(f"商品解锁状态变化，重新规划路线: {exc}")
            emit_run_status(
                "正在重新规划路线",
                str(exc),
                route=_summary_route_text(summary),
                **summary_profit_status_fields(summary),
            )
            try:
                go_home()
            except Exception as home_exc:
                logger.debug(f"重新规划前返回主界面失败，继续尝试规划: {home_exc}")
            new_route, new_summary, error = select_planned_route(
                strategy=strategy,
                use_cache=True,
            )
            if error or not new_route:
                error = error or "商品解锁状态变化后没有计算出新路线"
                emit_run_status("重新规划失败", error)
                return PlannedBusinessResult(False, True, route, summary, error)
            route, summary = new_route, new_summary
            emit_run_status(
                "已重新规划路线",
                "商品解锁状态已更新，正在按新路线继续执行",
                route=_summary_route_text(summary),
                **summary_profit_status_fields(summary),
            )
            continue
        if not ok or control_state.STOP:
            break
        emit_run_status(
            "准备下一轮跑商",
            "本轮完成，继续按当前路线循环",
            route=_summary_route_text(summary),
            **summary_profit_status_fields(summary),
        )
    if ok and account_config_auto_enabled():
        try:
            from auto.run_business.account_profile import analyze_account_profile
            from auto.run_business.config_updates import update_trade_account_profile

            emit_run_status(
                "正在刷新账号配置",
                "跑商完成后正在检查货舱、城市声望和乘员共振",
                route=_summary_route_text(summary),
                **summary_profit_status_fields(summary),
            )
            profile = analyze_account_profile()
            if profile.ok:
                update_trade_account_profile(
                    cargo_capacity=profile.cargo_capacity,
                    prestige_by_city=profile.prestige_by_city,
                    role_resonance=profile.role_resonance,
                    unavailable_cities=profile.unavailable_cities,
                    reason="跑商完成后刷新",
                )
            else:
                logger.warning(f"跑商完成后刷新账号配置失败: {profile.error}")
        except Exception as exc:
            logger.exception(f"跑商完成后刷新账号配置异常: {exc}")
    return PlannedBusinessResult(
        ok,
        True,
        route,
        summary,
        None if ok else "自动规划跑商失败",
    )
