from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path(
    r"F:\dev\koishi-resonance-columba-bot\external\resonance-columba-bot\src\data\fatigue.ts"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "resources" / "goods" / "CityFatigueData2026.json"

CITY_ALIASES = {
    "七号自由港": "7号自由港",
}


def normalize_city_name(name: str) -> str:
    return CITY_ALIASES.get(name, name)


def parse_fatigue_ts(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'cities:\s*\[\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\]\s*,\s*fatigue:\s*(\d+)',
        re.MULTILINE,
    )
    routes = []
    for match in pattern.finditer(text):
        city_a = normalize_city_name(match.group(1))
        city_b = normalize_city_name(match.group(2))
        routes.append(
            {
                "cities": [city_a, city_b],
                "fatigue": int(match.group(3)),
            }
        )
    return routes


def route_map(routes: list[dict]) -> dict[str, int]:
    data: dict[str, int] = {}
    for route in routes:
        city_a, city_b = route["cities"]
        fatigue = int(route["fatigue"])
        data[f"{city_a}-{city_b}"] = fatigue
        data[f"{city_b}-{city_a}"] = fatigue
    return dict(sorted(data.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Import city fatigue data from columba-bot.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)
    routes = parse_fatigue_ts(source)
    if not routes:
        raise SystemExit(f"no fatigue routes found in {source}")

    payload = {
        "schema_version": 1,
        "source": str(source),
        "note": "Imported from columba-bot src/data/fatigue.ts. Routes are undirected; map contains both directions.",
        "route_count": len(routes),
        "map_count": len(routes) * 2,
        "routes": routes,
        "map": route_map(routes),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output), "route_count": len(routes)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
