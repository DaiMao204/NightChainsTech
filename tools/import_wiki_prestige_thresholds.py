from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_SOURCE = Path(
    "G:/雷索纳斯wiki/文件/数据/2026/Data0522/HomeStationFactory.json"
)
DEFAULT_OUTPUT = Path("resources/goods/CityPrestigeThresholds2026.json")


def _rep_num(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def build_thresholds(data: list[dict[str, Any]], source: Path) -> dict[str, Any]:
    cities: dict[str, dict[str, int]] = {}
    default_thresholds: dict[str, int] = {}

    for station in data:
        name = str(station.get("name") or "").strip()
        rewards = station.get("repRewardList") or []
        if not name or not rewards:
            continue

        total = 0
        thresholds: dict[str, int] = {}
        for index, reward in enumerate(rewards, start=1):
            thresholds[str(index)] = total
            total += _rep_num((reward or {}).get("repNum"))

        cities[name] = thresholds
        if len(thresholds) > len(default_thresholds):
            default_thresholds = thresholds

    return {
        "source": str(source),
        "description": (
            "Cumulative city reputation required for each prestige level. "
            "Derived from HomeStationFactory.repRewardList[].repNum."
        ),
        "default": default_thresholds,
        "cities": cities,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import city prestige thresholds from wiki HomeStationFactory data."
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    data = json.loads(args.source.read_text(encoding="utf-8"))
    payload = build_thresholds(data, args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(args.out),
                "city_count": len(payload["cities"]),
                "default_levels": len(payload["default"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
