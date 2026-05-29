from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auto.run_business.planner import load_default_tired_data, normalize_city_name

DEFAULT_INPUT = PROJECT_ROOT / "resources" / "goods" / "ColumbaTradeData2026.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "resources" / "goods" / "ColumbaLocalMarketData2026.json"


def as_positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def build_local_market_data(columba_data: dict[str, Any], input_path: Path = DEFAULT_INPUT) -> dict[str, Any]:
    buy_goods: dict[str, dict[str, dict[str, Any]]] = {}
    buy_prices: dict[str, dict[str, dict[str, Any]]] = {}
    sell_prices: dict[str, dict[str, dict[str, Any]]] = {}

    for product in columba_data.get("products") or []:
        if not isinstance(product, dict):
            continue
        product_name = product.get("name")
        if not product_name or product.get("type") == "Craft":
            continue

        buy_lot_by_city = product.get("buyLot") or {}
        buy_price_by_city = product.get("buyPrices") or {}
        sell_price_by_city = product.get("sellPrices") or {}

        for raw_city, raw_price in buy_price_by_city.items():
            price = as_positive_int(raw_price)
            if price is None:
                continue
            city = normalize_city_name(raw_city)
            stock = as_positive_int(buy_lot_by_city.get(raw_city) or buy_lot_by_city.get(city)) or 1
            buy_goods.setdefault(city, {})[product_name] = {
                "isSpeciality": product.get("type") == "Special",
                "num": stock,
                "stock": stock,
                "base_price": price,
            }
            buy_prices.setdefault(city, {})[product_name] = {
                "price": price,
                "base_price": price,
                "stock": stock,
            }

        for raw_city, raw_price in sell_price_by_city.items():
            price = as_positive_int(raw_price)
            if price is None:
                continue
            city = normalize_city_name(raw_city)
            sell_prices.setdefault(city, {})[product_name] = {
                "price": price,
                "base_price": price,
            }

    return {
        "schema_version": 1,
        "source": {
            "project": "resonance-columba-bot",
            "input": str(input_path),
            "note": "Static baseline market data generated from columba-bot product buy/sell prices.",
        },
        "buy_goods": dict(sorted((city, dict(sorted(goods.items()))) for city, goods in buy_goods.items())),
        "buy_prices": dict(sorted((city, dict(sorted(goods.items()))) for city, goods in buy_prices.items())),
        "sell_prices": dict(sorted((city, dict(sorted(goods.items()))) for city, goods in sell_prices.items())),
        "tired": load_default_tired_data(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build local baseline market data from exported columba-bot trade data.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    columba_data = json.loads(input_path.read_text(encoding="utf-8"))
    payload = build_local_market_data(columba_data, input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "input": str(input_path),
                "output": str(output_path),
                "buy_cities": len(payload["buy_goods"]),
                "sell_cities": len(payload["sell_prices"]),
                "buy_items": sum(len(goods) for goods in payload["buy_goods"].values()),
                "sell_items": sum(len(goods) for goods in payload["sell_prices"].values()),
                "fatigue_routes": len(payload["tired"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
