"""
Probe visible map icons by clicking candidates and reading the right-side city panel.

Run this on the map page after zooming out. It does not click travel buttons.
"""

import argparse
import difflib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2 as cv
import numpy as np
from loguru import logger

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from core.control.control import connect, input_tap, screenshot_image
from core.image.ocr import predict


PROBE_DIR = project_root / "diagnostics" / "probes"
MAP_TOP = 90
MAP_BOTTOM = 705
SAFE_X_MIN = 0
SAFE_X_MAX = 1279
SAFE_Y_MIN = MAP_TOP
SAFE_Y_MAX = MAP_BOTTOM
ZOOM_X_MIN = 1100
ZOOM_X_MAX = 1230
ZOOM_Y_MIN = 320
MAIN_QUEST_X_MIN = 850
MAIN_QUEST_X_MAX = 1225
MAIN_QUEST_Y_MIN = 625
MAIN_QUEST_Y_MAX = 705


def load_known_city_names() -> list[str]:
    names: set[str] = set()
    for path in [
        project_root / "resources" / "map" / "CityMapSamples2026.json",
        project_root / "resources" / "goods" / "CityPosData.json",
        project_root / "resources" / "goods" / "CityGoodsSellData.json",
        project_root / "resources" / "stations" / "name2id.json",
    ]:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if path.name == "CityMapSamples2026.json":
            names.update(data.get("cities", {}).keys())
        else:
            names.update(data.keys())
    tired_path = project_root / "resources" / "goods" / "CityTiredData.json"
    if tired_path.exists():
        data = json.loads(tired_path.read_text(encoding="utf-8"))
        for route in data.keys():
            names.update(route.split("-", 1))
    return sorted(names)


KNOWN_CITY_NAMES = load_known_city_names()


def is_chinese_text(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def normalize_city_name(text: str) -> tuple[str, float]:
    if text in KNOWN_CITY_NAMES:
        return text, 1.0
    matches = difflib.get_close_matches(text, KNOWN_CITY_NAMES, n=1, cutoff=0.58)
    if not matches:
        return text, 0.0
    name = matches[0]
    return name, difflib.SequenceMatcher(None, text, name).ratio()


def close_panel():
    input_tap((610, 300))
    time.sleep(0.4)


def is_right_zoom_control(point: tuple[int, int]) -> bool:
    x, y = point
    return ZOOM_X_MIN <= x <= ZOOM_X_MAX and ZOOM_Y_MIN <= y <= MAP_BOTTOM


def is_main_quest_prompt(point: tuple[int, int]) -> bool:
    x, y = point
    return MAIN_QUEST_X_MIN <= x <= MAIN_QUEST_X_MAX and MAIN_QUEST_Y_MIN <= y <= MAIN_QUEST_Y_MAX


def is_forbidden_ui_point(point: tuple[int, int]) -> bool:
    return is_right_zoom_control(point) or is_main_quest_prompt(point)


def is_safe_inner_point(point: tuple[int, int]) -> bool:
    x, y = point
    return (
        SAFE_X_MIN <= x <= SAFE_X_MAX
        and SAFE_Y_MIN <= y <= SAFE_Y_MAX
        and not is_forbidden_ui_point(point)
    )


def find_icon_candidates(image, *, include_edge: bool = False) -> list[tuple[int, int]]:
    hsv = cv.cvtColor(image, cv.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 120)).astype("uint8") * 255

    # Ignore persistent UI regions: top bar, lower-right zoom controls, and main quest prompt.
    mask[:MAP_TOP, :] = 0
    mask[MAP_BOTTOM:, :] = 0
    mask[ZOOM_Y_MIN:MAP_BOTTOM, ZOOM_X_MIN:ZOOM_X_MAX] = 0
    mask[MAIN_QUEST_Y_MIN:MAIN_QUEST_Y_MAX, MAIN_QUEST_X_MIN:MAIN_QUEST_X_MAX] = 0

    count, labels, stats, centers = cv.connectedComponentsWithStats(mask)
    candidates: list[tuple[int, int]] = []
    for index in range(1, count):
        x, y, w, h, area = stats[index]
        if not (30 <= area <= 700 and 6 <= w <= 42 and 6 <= h <= 42):
            continue
        cx, cy = centers[index]
        point = (int(round(cx)), int(round(cy)))
        if is_forbidden_ui_point(point):
            continue
        if not include_edge and not is_safe_inner_point(point):
            continue
        if all(abs(point[0] - p[0]) > 18 or abs(point[1] - p[1]) > 18 for p in candidates):
            candidates.append(point)
    return sorted(candidates, key=lambda p: (p[1], p[0]))


def read_city_panel(image) -> dict | None:
    data = predict(image, no_crop=True)
    has_travel_button = any(item["text"] == "前往目的地" for item in data)
    has_current_station_actions = any(
        item["text"] in {"拖车服务", "行驶辅助", "补充燃料", "招揽乘客", "交易所", "每周新闻"}
        for item in data
    )
    if not has_travel_button and not has_current_station_actions:
        return None

    title_candidates = [
        item
        for item in data
        if is_chinese_text(item["text"])
        and ":" not in item["text"]
        and "：" not in item["text"]
        and len(item["text"]) <= 10
        and 650 <= item["position"][0][0] <= 960
        and 80 <= item["position"][0][1] <= 150
    ]
    if not title_candidates:
        return None

    title = max(title_candidates, key=lambda item: item["score"])
    raw_name = title["text"]
    name, match_score = normalize_city_name(raw_name)
    return {
        "name": name,
        "raw_name": raw_name,
        "name_match_score": match_score,
        "score": title["score"],
        "position": title["position"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--close-first", action="store_true")
    parser.add_argument("--include-edge", action="store_true", help="also probe edge candidates; unsafe for normal use")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.verbose:
        logger.remove()

    if not connect():
        print("Failed to connect emulator. Check ADB/MuMu settings first.")
        return 1

    if args.close_first:
        close_panel()

    base_image = screenshot_image()
    candidates = find_icon_candidates(base_image, include_edge=args.include_edge)[: args.limit]
    print(f"Found {len(candidates)} icon candidates")

    results = []
    seen_names = set()
    for point in candidates:
        input_tap(point)
        time.sleep(0.8)
        image = screenshot_image()
        panel = read_city_panel(image)
        if panel and panel["name"] not in seen_names:
            seen_names.add(panel["name"])
            row = {"screen_point": list(point), **panel}
            results.append(row)
            print(f"{point}: {panel['name']} ({panel['score']:.3f})")
        close_panel()

    PROBE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = PROBE_DIR / f"{timestamp}_visible_map_cities.json"
    out_path.write_text(
        json.dumps({"candidates": candidates, "cities": results}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Saved probe: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
