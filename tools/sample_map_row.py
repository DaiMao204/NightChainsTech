"""
Sample visible cities while moving across one map row.

Run this on the zoomed-out map. The script probes the current viewport, then
drags the map one viewport at a time. It never clicks the travel button.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2 as cv
from loguru import logger

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from core.control.control import connect, input_swipe, screenshot_image
from tools.probe_visible_map_cities import (
    close_panel,
    find_icon_candidates,
    read_city_panel,
)


ROW_DIR = project_root / "diagnostics" / "map_rows"


def probe_viewport(limit: int) -> tuple[list[dict], list[tuple[int, int]], object]:
    close_panel()
    image = screenshot_image()
    candidates = find_icon_candidates(image)[:limit]
    cities = []
    seen = set()

    for point in candidates:
        from core.control.control import input_tap

        input_tap(point)
        time.sleep(0.75)
        selected_image = screenshot_image()
        panel = read_city_panel(selected_image)
        if panel and panel["name"] not in seen:
            seen.add(panel["name"])
            cities.append({"screen_point": list(point), **panel})
        close_panel()

    return cities, candidates, image


def drag(direction: str, distance: int, duration: int):
    if direction == "east":
        input_swipe((900, 360), (900 - distance, 360), duration)
    elif direction == "west":
        input_swipe((360, 360), (360 + distance, 360), duration)
    elif direction == "south":
        input_swipe((640, 520), (640, 520 - distance), duration)
    elif direction == "north":
        input_swipe((640, 220), (640, 220 + distance), duration)
    else:
        raise ValueError(f"Unsupported direction: {direction}")
    time.sleep(1.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--direction", choices=["east", "west", "south", "north"], default="east")
    parser.add_argument("--steps", type=int, default=4)
    parser.add_argument("--limit", type=int, default=35)
    parser.add_argument("--distance", type=int, default=520)
    parser.add_argument("--duration", type=int, default=900)
    parser.add_argument("--label", default="row")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.verbose:
        logger.remove()

    if not connect():
        print("Failed to connect emulator. Check ADB/MuMu settings first.")
        return 1

    ROW_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = ROW_DIR / f"{timestamp}_{args.label}_{args.direction}"
    run_dir.mkdir(parents=True, exist_ok=True)

    samples = []
    for index in range(args.steps):
        cities, candidates, image = probe_viewport(args.limit)
        image_path = run_dir / f"step_{index:02d}.png"
        cv.imwrite(str(image_path), image)
        samples.append(
            {
                "step": index,
                "image": str(image_path),
                "candidate_count": len(candidates),
                "candidates": [list(point) for point in candidates],
                "cities": cities,
            }
        )
        names = ", ".join(city["name"] for city in cities) or "none"
        print(f"step {index}: {names}")
        if index < args.steps - 1:
            drag(args.direction, args.distance, args.duration)

    out_path = run_dir / "samples.json"
    out_path.write_text(
        json.dumps(
            {
                "direction": args.direction,
                "steps": args.steps,
                "distance": args.distance,
                "duration": args.duration,
                "samples": samples,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"Saved row samples: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
