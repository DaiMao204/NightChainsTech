"""
Detect stable map anchors from saved station-map screenshots.

The animated map background is intentionally ignored. This tool extracts only
stable layers that are useful for navigation:
- colored station/city marker candidates
- route/rail line pixels and line segments
- known city-name OCR boxes when they are large enough to read
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

import cv2 as cv
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

from core.image.ocr import predict


MAP_TOP = 90
MAP_BOTTOM = 705
SCREEN_WIDTH = 1280
ZOOM_X_MIN = 1100
ZOOM_X_MAX = 1230
ZOOM_Y_MIN = 320
MAIN_QUEST_X_MIN = 850
MAIN_QUEST_X_MAX = 1225
MAIN_QUEST_Y_MIN = 625
MAIN_QUEST_Y_MAX = 705


def load_known_city_names() -> list[str]:
    path = PROJECT_ROOT / "resources" / "map" / "CityMapSamples2026.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return sorted(data.get("cities", {}).keys())


KNOWN_CITY_NAMES = load_known_city_names()


def is_chinese_text(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def normalize_city_name(text: str) -> tuple[str, float]:
    clean = text.strip().replace(" ", "")
    if clean in KNOWN_CITY_NAMES:
        return clean, 1.0
    matches = difflib.get_close_matches(clean, KNOWN_CITY_NAMES, n=1, cutoff=0.58)
    if not matches:
        return clean, 0.0
    name = matches[0]
    return name, difflib.SequenceMatcher(None, clean, name).ratio()


def box_center(position: list[list[float]]) -> tuple[int, int]:
    xs = [point[0] for point in position]
    ys = [point[1] for point in position]
    return int(round(sum(xs) / len(xs))), int(round(sum(ys) / len(ys)))


def is_right_zoom_control(point: tuple[int, int]) -> bool:
    x, y = point
    return ZOOM_X_MIN <= x <= ZOOM_X_MAX and ZOOM_Y_MIN <= y <= MAP_BOTTOM


def is_main_quest_prompt(point: tuple[int, int]) -> bool:
    x, y = point
    return MAIN_QUEST_X_MIN <= x <= MAIN_QUEST_X_MAX and MAIN_QUEST_Y_MIN <= y <= MAIN_QUEST_Y_MAX


def valid_map_point(point: tuple[int, int]) -> bool:
    x, y = point
    return 0 <= x < SCREEN_WIDTH and MAP_TOP <= y <= MAP_BOTTOM and not is_right_zoom_control(point) and not is_main_quest_prompt(point)


def stable_region_mask(shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[MAP_TOP:MAP_BOTTOM, :] = 255
    mask[ZOOM_Y_MIN:MAP_BOTTOM, ZOOM_X_MIN:ZOOM_X_MAX] = 0
    mask[MAIN_QUEST_Y_MIN:MAIN_QUEST_Y_MAX, MAIN_QUEST_X_MIN:MAIN_QUEST_X_MAX] = 0
    return mask


def detect_city_icons(image: np.ndarray) -> list[dict]:
    hsv = cv.cvtColor(image, cv.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 120)).astype("uint8") * 255
    mask = cv.bitwise_and(mask, stable_region_mask(mask.shape))

    count, labels, stats, centers = cv.connectedComponentsWithStats(mask)
    anchors: list[dict] = []
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if not (30 <= area <= 700 and 6 <= width <= 42 and 6 <= height <= 42):
            continue
        point = (int(round(centers[index][0])), int(round(centers[index][1])))
        if not valid_map_point(point):
            continue

        anchors.append(
            {
                "type": "city_icon",
                "center": list(point),
                "bbox": [int(x), int(y), int(width), int(height)],
                "area": int(area),
            }
        )

    return sorted(anchors, key=lambda item: (item["center"][1], item["center"][0]))


def detect_city_labels(image: np.ndarray) -> list[dict]:
    anchors: list[dict] = []
    for item in predict(image, no_crop=True):
        text = item["text"].strip().replace(" ", "")
        if not text or not is_chinese_text(text) or len(text) > 12:
            continue

        center = box_center(item["position"])
        if not valid_map_point(center):
            continue

        name, match_score = normalize_city_name(text)
        if name not in KNOWN_CITY_NAMES or match_score < 0.58:
            continue

        anchors.append(
            {
                "type": "city_label",
                "name": name,
                "raw_text": text,
                "center": list(center),
                "match_score": round(match_score, 4),
                "ocr_score": round(float(item["score"]), 4),
                "position": item["position"],
            }
        )

    return anchors


def detect_route_mask(image: np.ndarray) -> tuple[np.ndarray, list[dict]]:
    hsv = cv.cvtColor(image, cv.COLOR_BGR2HSV)

    # Stable route colors are blue/cyan-grey strokes. They are not very bright,
    # so threshold by hue/saturation first and let geometry reject background
    # contour noise later.
    cyan_grey = (
        (hsv[:, :, 0] >= 84)
        & (hsv[:, :, 0] <= 112)
        & (hsv[:, :, 1] >= 40)
        & (hsv[:, :, 1] <= 170)
        & (hsv[:, :, 2] >= 42)
        & (hsv[:, :, 2] <= 150)
    )
    active_blue = (
        (hsv[:, :, 0] >= 108)
        & (hsv[:, :, 0] <= 135)
        & (hsv[:, :, 1] >= 70)
        & (hsv[:, :, 2] >= 80)
    )
    purple_route = (
        (hsv[:, :, 0] >= 136)
        & (hsv[:, :, 0] <= 170)
        & (hsv[:, :, 1] >= 45)
        & (hsv[:, :, 2] >= 80)
    )
    mask = (cyan_grey | active_blue | purple_route).astype("uint8") * 255
    mask = cv.bitwise_and(mask, stable_region_mask(mask.shape))

    # Remove tiny sparkles and city icons; keep elongated route strokes.
    mask = cv.morphologyEx(mask, cv.MORPH_OPEN, np.ones((2, 2), np.uint8))
    mask = cv.morphologyEx(mask, cv.MORPH_CLOSE, np.ones((3, 3), np.uint8))

    lines_raw = cv.HoughLinesP(mask, 1, np.pi / 180, threshold=24, minLineLength=38, maxLineGap=12)
    segments: list[dict] = []
    if lines_raw is not None:
        for line in lines_raw[:, 0, :]:
            x1, y1, x2, y2 = [int(value) for value in line]
            if not valid_map_point((x1, y1)) and not valid_map_point((x2, y2)):
                continue
            length = float(np.hypot(x2 - x1, y2 - y1))
            segments.append(
                {
                    "type": "route_segment",
                    "start": [x1, y1],
                    "end": [x2, y2],
                    "length": round(length, 2),
                }
            )

    segments.sort(key=lambda item: item["length"], reverse=True)
    return mask, segments


def draw_overlay(image: np.ndarray, route_mask: np.ndarray, anchors: list[dict], segments: list[dict]) -> np.ndarray:
    overlay = image.copy()
    route_layer = np.zeros_like(image)
    route_layer[:, :, 1] = route_mask
    route_layer[:, :, 2] = route_mask // 2
    overlay = cv.addWeighted(overlay, 0.72, route_layer, 0.55, 0)

    for segment in segments[:80]:
        start = tuple(segment["start"])
        end = tuple(segment["end"])
        cv.line(overlay, start, end, (0, 255, 255), 1, cv.LINE_AA)

    for anchor in anchors:
        center = tuple(anchor["center"])
        if anchor["type"] == "city_icon":
            cv.circle(overlay, center, 10, (0, 165, 255), 2, cv.LINE_AA)
        elif anchor["type"] == "city_label":
            cv.circle(overlay, center, 14, (255, 80, 255), 2, cv.LINE_AA)
            cv.putText(overlay, anchor["name"], (center[0] + 8, center[1] - 8), cv.FONT_HERSHEY_SIMPLEX, 0.5, (255, 80, 255), 1, cv.LINE_AA)

    cv.rectangle(overlay, (0, MAP_TOP), (SCREEN_WIDTH - 1, MAP_BOTTOM), (80, 220, 80), 1)
    cv.rectangle(overlay, (ZOOM_X_MIN, ZOOM_Y_MIN), (ZOOM_X_MAX, MAP_BOTTOM), (0, 0, 255), 2)
    cv.rectangle(overlay, (MAIN_QUEST_X_MIN, MAIN_QUEST_Y_MIN), (MAIN_QUEST_X_MAX, MAIN_QUEST_Y_MAX), (0, 0, 255), 2)
    return overlay


def relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def process_image(path: Path, out_dir: Path) -> dict:
    image = cv.imread(str(path))
    if image is None:
        raise FileNotFoundError(path)

    icons = detect_city_icons(image)
    labels = detect_city_labels(image)
    route_mask, segments = detect_route_mask(image)
    anchors = icons + labels

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        relative = path.resolve().relative_to(PROJECT_ROOT)
        stem = "__".join(relative.with_suffix("").parts)
    except ValueError:
        stem = path.stem
    overlay_path = out_dir / f"{stem}_anchors.png"
    mask_path = out_dir / f"{stem}_route_mask.png"
    json_path = out_dir / f"{stem}_anchors.json"
    cv.imwrite(str(overlay_path), draw_overlay(image, route_mask, anchors, segments))
    cv.imwrite(str(mask_path), route_mask)

    data = {
        "image": relpath(path),
        "overlay": relpath(overlay_path),
        "route_mask": relpath(mask_path),
        "city_icon_count": len(icons),
        "city_label_count": len(labels),
        "route_segment_count": len(segments),
        "anchors": anchors,
        "route_segments": segments[:120],
    }
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data | {"json": relpath(json_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--out-dir", type=Path, default=PROJECT_ROOT / "diagnostics" / "map_anchors")
    args = parser.parse_args()

    summaries = []
    for image_path in args.images:
        summary = process_image(image_path, args.out_dir)
        summaries.append(summary)
        print(
            f"{image_path}: icons={summary['city_icon_count']} "
            f"labels={summary['city_label_count']} route_segments={summary['route_segment_count']}"
        )

    index_path = args.out_dir / "index.json"
    index_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"index={index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
