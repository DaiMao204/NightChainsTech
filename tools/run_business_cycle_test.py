from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auto.run_business.main import city_sell_data, run
from core.model.city_goods import RouteModel, RoutesModel


def select_goods(city: str, good_name: str | None) -> dict:
    goods = city_sell_data[city]
    if not good_name:
        return goods
    if good_name not in goods:
        raise KeyError(f"{good_name} is not configured for {city}")
    return {good_name: goods[good_name]}


def build_routes(
    buy_city: str,
    sell_city: str,
    haggle: int,
    book: int,
    buy_good: str | None,
    return_good: str | None,
) -> RoutesModel:
    return RoutesModel(
        city_data=[
            RouteModel(
                buy_city_name=buy_city,
                sell_city_name=sell_city,
                haggle_num=haggle,
                book=book,
                goods_data=select_goods(buy_city, buy_good),
            ),
            RouteModel(
                buy_city_name=sell_city,
                sell_city_name=buy_city,
                haggle_num=haggle,
                book=book,
                goods_data=select_goods(sell_city, return_good),
            ),
        ],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one two-city business cycle.")
    parser.add_argument("buy_city")
    parser.add_argument("sell_city")
    parser.add_argument("--haggle", type=int, default=0)
    parser.add_argument("--book", type=int, default=0)
    parser.add_argument("--buy-good")
    parser.add_argument("--return-good")
    args = parser.parse_args()

    routes = build_routes(
        args.buy_city,
        args.sell_city,
        args.haggle,
        args.book,
        args.buy_good,
        args.return_good,
    )
    result = run(routes)
    print(f"BUSINESS_CYCLE_RESULT={result}")
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
