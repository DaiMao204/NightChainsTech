from __future__ import annotations

from typing import Any

from core.model.city_goods import RoutesModel


def _route_text(routes: RoutesModel) -> str:
    legs = routes.city_data or []
    if not legs:
        return ""
    first = legs[0]
    buy_city = str(getattr(first, "buy_city_name", "") or "")
    sell_city = str(getattr(first, "sell_city_name", "") or "")
    if buy_city and sell_city:
        return f"{buy_city} <-> {sell_city}"
    return buy_city or sell_city


def _route_profit_text(routes: RoutesModel) -> str:
    if routes.jiaozi_profit is not None and routes.tiemeng_profit is not None:
        return f"利润 交子{routes.jiaozi_profit}/铁盟币{routes.tiemeng_profit}"
    return f"利润 {routes.profit}"


def _leg_text(leg: Any) -> str:
    haggle_num = int(getattr(leg, "haggle_num", 0) or 0)
    haggle = f"抬砍{min(20, haggle_num)}%" if haggle_num > 0 else "不抬砍"
    return (
        f"{getattr(leg, 'buy_city_name', '')}->{getattr(leg, 'sell_city_name', '')}："
        f"{getattr(leg, 'book', 0)}书，{haggle}，"
        f"疲劳{getattr(leg, 'city_tired', '-')}"
    )


def routes_status_overview(routes: RoutesModel) -> str:
    legs = routes.city_data or []
    parts = [_route_text(routes), _route_profit_text(routes)]
    if routes.book is not None and routes.book >= 0:
        parts.append(f"共{routes.book}书")
    if routes.city_tired is not None:
        parts.append(f"总疲劳{routes.city_tired}")
    leg_text = " | ".join(_leg_text(leg) for leg in legs)
    overview = "，".join(part for part in parts if part)
    return f"{overview}；{leg_text}" if leg_text else overview


def _with_optional_currency_fields(fields: dict[str, Any], source: Any) -> dict[str, Any]:
    for key in (
        "jiaozi_profit",
        "tiemeng_profit",
        "jiaozi_general_profit_index",
        "tiemeng_general_profit_index",
        "mixed_currency_profit",
    ):
        value = source.get(key) if isinstance(source, dict) else getattr(source, key, None)
        if value is not None:
            fields[key] = value
    return fields


def routes_profit_status_fields(routes: RoutesModel) -> dict[str, Any]:
    reference_profit = routes.general_profit_index
    mixed_currency_profit = routes.jiaozi_profit is not None and routes.tiemeng_profit is not None
    fields: dict[str, Any] = {
        "profit": routes.profit,
        "total_profit": None if mixed_currency_profit else routes.profit,
        "mixed_currency_profit": mixed_currency_profit,
        "general_profit_index": reference_profit,
        "reference_profit": reference_profit,
        "reference_profit_label": (
            "总和综合参考利润"
            if mixed_currency_profit
            else "综合参考利润"
        ),
        "route_summary": routes_status_overview(routes),
    }
    return _with_optional_currency_fields(fields, routes)


def summary_profit_status_fields(summary: dict[str, Any] | None) -> dict[str, Any]:
    if not summary:
        return {}
    reference_profit = summary.get("reference_profit")
    if reference_profit is None:
        reference_profit = summary.get("general_profit_index")
    mixed_currency_profit = bool(summary.get("mixed_currency_profit"))
    total_profit = summary.get("total_profit")
    if total_profit is None and not mixed_currency_profit:
        total_profit = summary.get("profit")

    fields: dict[str, Any] = {
        "profit": summary.get("profit"),
        "total_profit": total_profit,
        "mixed_currency_profit": mixed_currency_profit,
        "general_profit_index": summary.get("general_profit_index"),
        "reference_profit": reference_profit,
        "reference_profit_label": summary.get("reference_profit_label") or "综合参考利润",
    }
    return _with_optional_currency_fields(fields, summary)
