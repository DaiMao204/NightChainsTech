from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auto.run_business.planner import (
    DEFAULT_MARKET_CACHE_TTL,
    MIXED_CURRENCY_PRIORITIES,
    RoutePlanOptions,
    load_market_data,
    market_data_from_payload,
    normalize_city_pairs,
    plan_two_city_routes,
    summarize_routes,
)
from auto.run_business.planner_config import load_trade_planner_config, route_plan_options_from_config


def parse_city_set(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    result: set[str] = set()
    for value in values:
        result.update(city.strip() for city in value.split(",") if city.strip())
    return result or None


def parse_int_mapping(values: list[str] | None) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values or []:
        for item in value.split(","):
            if not item.strip():
                continue
            name, sep, raw_number = item.partition("=")
            if not sep:
                raise ValueError(f"expected NAME=NUMBER: {item}")
            result[name.strip()] = int(raw_number.strip())
    return result


def parse_event_mapping(values: list[str] | None) -> dict[str, dict[str, bool]]:
    result: dict[str, dict[str, bool]] = {}
    for value in values or []:
        for item in value.split(","):
            if not item.strip():
                continue
            name, sep, raw_enabled = item.partition("=")
            if not sep:
                raise ValueError(f"expected EVENT=true/false: {item}")
            enabled = raw_enabled.strip().lower() in {"1", "true", "yes", "on"}
            result[name.strip()] = {"activated": enabled}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan high-value two-city business routes.")
    parser.add_argument("--api-url", help="Optional market-data API endpoint.")
    parser.add_argument("--api-file", help="Optional saved market-data JSON payload for offline testing.")
    parser.add_argument("--cache-ttl", type=float, default=DEFAULT_MARKET_CACHE_TTL, help="Market API cache TTL in seconds. Default: 300.")
    parser.add_argument("--refresh-cache", action="store_true", help="Request the API once and update the local cache.")
    parser.add_argument("--no-cache", action="store_true", help="Do not read or write the local market API cache.")
    parser.add_argument(
        "--use-local-baseline",
        action="store_true",
        help="Use static columba-bot baseline prices when --api-url/--api-file is omitted. This is for smoke tests, not current best routes.",
    )
    parser.add_argument("--planner-config", help="Optional TradePlanner JSON config. Defaults to config/trade_planner.json when it exists.")
    parser.add_argument("--no-planner-config", action="store_true", help="Ignore config/trade_planner.json.")
    parser.add_argument(
        "--strategy",
        choices=("profit", "tired_profit", "book_profit", "general_profit_index"),
        default="general_profit_index",
    )
    parser.add_argument(
        "--mixed-currency-priority",
        choices=MIXED_CURRENCY_PRIORITIES,
        default="total",
        help="Wulinyuan mixed-currency priority: total, jiaozi, or tiemeng.",
    )
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--max-goods-num", type=int, help="Cargo capacity. Default uses columba-bot BotConfig maxLot.")
    parser.add_argument("--max-restock", type=int, help="Total restock books for round-trip planning. Default uses columba-bot BotConfig.")
    parser.add_argument("--no-compare-no-return-bargain", action="store_true")
    parser.add_argument("--include-city", action="append", help="Only plan routes using these cities. Comma-separated values are accepted.")
    parser.add_argument("--exclude-city", action="append", help="Skip routes using these cities. Comma-separated values are accepted.")
    parser.add_argument("--allowed-pair", action="append", help="Only plan these city pairs, e.g. 武林源-贡露城.")
    parser.add_argument("--blocked-pair", action="append", help="Skip these city pairs, e.g. 海角城-汇流塔.")
    parser.add_argument("--allowed-good", action="append", help="Only use these goods. Comma-separated values are accepted.")
    parser.add_argument("--blocked-good", action="append", help="Never use these goods. Comma-separated values are accepted.")
    parser.add_argument("--locked-good", action="append", help="Mark goods as locked/unavailable. Comma-separated values are accepted.")
    parser.add_argument("--unlocked-good", action="append", help="Override goods as unlocked. Comma-separated values are accepted.")
    parser.add_argument("--role", action="append", help="Override role resonance, e.g. 朱利安=4.")
    parser.add_argument("--disable-role", action="append", help="Disable role bonuses. Comma-separated values are accepted.")
    parser.add_argument("--prestige", action="append", help="Override city prestige level, e.g. 修格里城=20.")
    parser.add_argument("--event", action="append", help="Override event activation, e.g. 红茶战争=false.")
    parser.add_argument("--no-default-roles", action="store_true", help="Do not start from columba-bot default role resonance config.")
    parser.add_argument("--no-default-product-locks", action="store_true", help="Ignore columba-bot default product unlock config.")
    args = parser.parse_args()

    if args.api_file:
        payload = json.loads(Path(args.api_file).read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
            payload = payload["data"]
        market = market_data_from_payload(payload)
    else:
        market = load_market_data(
            args.api_url,
            cache_ttl=args.cache_ttl,
            use_cache=not args.no_cache,
            refresh_cache=args.refresh_cache,
            use_local_baseline=args.use_local_baseline,
        )
    options = route_plan_options_from_config(
        {} if args.no_planner_config else load_trade_planner_config(args.planner_config),
        RoutePlanOptions(strategy=args.strategy),
    )
    product_unlock_status = dict(options.product_unlock_status or {})
    product_unlock_status.update({good: False for good in parse_city_set(args.locked_good) or set()})
    product_unlock_status.update({good: True for good in parse_city_set(args.unlocked_good) or set()})
    option_overrides = {
        "strategy": args.strategy,
        "mixed_currency_priority": args.mixed_currency_priority,
        "product_unlock_status": product_unlock_status,
    }
    if args.max_goods_num is not None:
        option_overrides["max_goods_num"] = args.max_goods_num
    if args.max_restock is not None:
        option_overrides["max_restock"] = args.max_restock
    if (value := parse_city_set(args.include_city)) is not None:
        option_overrides["include_cities"] = value
    if (value := parse_city_set(args.exclude_city)) is not None:
        option_overrides["exclude_cities"] = value
    if (value := normalize_city_pairs(args.allowed_pair)) is not None:
        option_overrides["allowed_city_pairs"] = value
    if (value := normalize_city_pairs(args.blocked_pair)) is not None:
        option_overrides["blocked_city_pairs"] = value
    if (value := parse_city_set(args.allowed_good)) is not None:
        option_overrides["allowed_goods"] = value
    if (value := parse_city_set(args.blocked_good)) is not None:
        option_overrides["blocked_goods"] = value
    if args.no_compare_no_return_bargain:
        option_overrides["compare_no_return_bargain"] = False
    if args.role:
        option_overrides["roles"] = {
            role_name: {"resonance": resonance}
            for role_name, resonance in parse_int_mapping(args.role).items()
        }
    if args.no_default_roles:
        option_overrides["use_default_roles"] = False
    if (value := parse_city_set(args.disable_role)) is not None:
        option_overrides["disabled_roles"] = value
    if args.prestige:
        option_overrides["prestige_by_city"] = parse_int_mapping(args.prestige)
    if args.no_default_product_locks:
        option_overrides["use_default_product_unlock_status"] = False
    if args.event:
        option_overrides["events"] = parse_event_mapping(args.event)
    options = replace(options, **option_overrides)
    routes = plan_two_city_routes(market, options)
    summaries = [summarize_routes(route, args.strategy) for route in routes[: max(1, args.top)]]
    warnings = []
    if args.use_local_baseline and not args.api_url and not args.api_file:
        warnings.append("当前使用的是 columba-bot 静态基准价，只适合离线冒烟和公式对照；真实最佳路线仍需要实时 API 行情。")
    elif not summaries and not args.api_url and not args.api_file:
        warnings.append("本地旧商品资源缺少完整跨城价格矩阵，需要接入实时商品 API 后才能计算最佳路线。")
    print(
        json.dumps(
            {
                "ok": True,
                "strategy": args.strategy,
                "mixed_currency_priority": args.mixed_currency_priority,
                "count": len(summaries),
                "warnings": warnings,
                "routes": summaries,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
