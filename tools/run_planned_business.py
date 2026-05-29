from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auto.run_business.auto_route import run_planned_business
from auto.run_business.planner import (
    DEFAULT_MARKET_CACHE_TTL,
    MIXED_CURRENCY_PRIORITIES,
    normalize_city_pairs,
)


def parse_city_set(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    result: set[str] = set()
    for value in values:
        result.update(city.strip() for city in value.split(",") if city.strip())
    return result or None


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan a business route and optionally execute it.")
    parser.add_argument("--api-url", help="Optional market-data API endpoint.")
    parser.add_argument("--api-file", help="Optional saved market-data JSON payload for offline testing.")
    parser.add_argument("--cache-ttl", type=float, default=DEFAULT_MARKET_CACHE_TTL, help="Market API cache TTL in seconds. Default: 300.")
    parser.add_argument("--refresh-cache", action="store_true", help="Request the API once and update the local cache.")
    parser.add_argument("--no-cache", action="store_true", help="Do not read or write the local market API cache.")
    parser.add_argument(
        "--use-local-baseline",
        action="store_true",
        help="Use static columba-bot baseline prices only for dry-run smoke tests. Refused with --execute.",
    )
    parser.add_argument("--planner-config", help="Optional TradePlanner JSON config.")
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
    parser.add_argument("--route-index", type=int, default=0, help="0-based route rank to run.")
    parser.add_argument("--max-goods-num", type=int)
    parser.add_argument("--max-restock", type=int)
    parser.add_argument("--min-profit", type=int, default=1)
    parser.add_argument("--include-city", action="append", help="Only plan routes using these cities. Comma-separated values are accepted.")
    parser.add_argument("--exclude-city", action="append", help="Skip routes using these cities. Comma-separated values are accepted.")
    parser.add_argument("--allowed-pair", action="append", help="Only plan these city pairs, e.g. 武林源-贡露城.")
    parser.add_argument("--blocked-pair", action="append", help="Skip these city pairs, e.g. 海角城-汇流塔.")
    parser.add_argument("--execute", action="store_true", help="Actually run the selected route. Without this flag only prints the route.")
    args = parser.parse_args()
    if args.execute and args.use_local_baseline:
        print(
            json.dumps(
                {"ok": False, "error": "--use-local-baseline uses static prices and cannot be used with --execute"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    result = run_planned_business(
        api_url=args.api_url,
        api_file=args.api_file,
        strategy=args.strategy,
        mixed_currency_priority=args.mixed_currency_priority,
        route_index=args.route_index,
        max_goods_num=args.max_goods_num,
        max_restock=args.max_restock,
        planner_config=args.planner_config,
        include_cities=parse_city_set(args.include_city),
        exclude_cities=parse_city_set(args.exclude_city),
        allowed_city_pairs=normalize_city_pairs(args.allowed_pair),
        blocked_city_pairs=normalize_city_pairs(args.blocked_pair),
        min_profit=args.min_profit,
        cache_ttl=args.cache_ttl,
        use_cache=not args.no_cache,
        refresh_cache=args.refresh_cache,
        use_local_baseline=args.use_local_baseline,
        execute=args.execute,
    )
    payload = asdict(result)
    payload.pop("route", None)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
