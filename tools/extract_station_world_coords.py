"""
Extract station minimap coordinates from the wiki BinaryConfig export.

The source table is HomeStationFactory.json generated from BinaryConfig. Its
station x/y fields use Shoggolith City / 修格里城 as the (0, 0) center.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = Path(r"G:\雷索纳斯wiki\代码\Data\HomeStationFactory.json")
DEFAULT_OUT = PROJECT_ROOT / "resources" / "map" / "CityWorld2026.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def build_city_world(source_path: Path) -> dict:
    stations = load_json(source_path)
    visible = []
    hidden = []

    for station in stations:
        row = {
            "id": station.get("id"),
            "name": station.get("name"),
            "x": float(station.get("x", 0.0)),
            "y": float(station.get("y", 0.0)),
            "map_icon_path": station.get("mapIconPath", ""),
            "attached_to_city": station.get("attachedToCity", -1),
            "is_open": bool(station.get("isOpen")),
            "is_ban_stop": bool(station.get("isBanStop")),
            "is_show_in_map": bool(station.get("isShowInMap")),
        }
        if row["is_show_in_map"]:
            visible.append(row)
        else:
            hidden.append(row)

    visible.sort(key=lambda item: (item["y"], item["x"], item["name"]))
    hidden.sort(key=lambda item: (item["y"], item["x"], item["name"]))

    return {
        "schema_version": 1,
        "source": str(source_path),
        "coordinate_space": "HomeStationFactory minimap coordinates; 修格里城 is (0, 0); +x east/right, +y north/up in config space",
        "station_count": len(visible),
        "hidden_station_count": len(hidden),
        "stations": visible,
        "hidden_stations": hidden,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    data = build_city_world(args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved station world coordinates: {args.out}")
    print(f"Visible stations: {data['station_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
