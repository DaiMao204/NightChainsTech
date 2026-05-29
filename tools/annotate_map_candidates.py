"""
Create a no-click map candidate overlay for manual calibration.

This tool may capture a screenshot, but it never taps or swipes. Use it before
changing live map click rules.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import cv2 as cv

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from core.control.control import connect, screenshot_image
from core.preset.map_navigation import (
    MAP_BOTTOM,
    MAP_TOP,
    MAIN_QUEST_X_MAX,
    MAIN_QUEST_X_MIN,
    MAIN_QUEST_Y_MAX,
    MAIN_QUEST_Y_MIN,
    SAFE_X_MAX,
    SAFE_X_MIN,
    SAFE_Y_MAX,
    SAFE_Y_MIN,
    ZOOM_X_MAX,
    ZOOM_X_MIN,
    ZOOM_Y_MIN,
    city_sample_points,
    find_icon_candidates,
    find_target_label_probes,
    find_white_marker_candidates,
    is_forbidden_ui_point,
    is_main_quest_prompt,
    is_right_zoom_control,
    is_safe_inner_point,
)


OUT_DIR = project_root / "diagnostics" / "candidate_overlays"


def draw_label(image, text: str, origin: tuple[int, int], color: tuple[int, int, int]):
    cv.putText(image, text, origin, cv.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 3, cv.LINE_AA)
    cv.putText(image, text, origin, cv.FONT_HERSHEY_SIMPLEX, 0.48, color, 1, cv.LINE_AA)


def draw_regions(image):
    cv.rectangle(image, (SAFE_X_MIN, SAFE_Y_MIN), (SAFE_X_MAX, SAFE_Y_MAX), (60, 220, 60), 2)
    draw_label(image, "MAP CLICKABLE BODY", (SAFE_X_MIN + 8, SAFE_Y_MIN - 8), (60, 220, 60))

    cv.rectangle(image, (ZOOM_X_MIN, ZOOM_Y_MIN), (ZOOM_X_MAX, MAP_BOTTOM), (0, 0, 255), 2)
    draw_label(image, "NO CLICK: ZOOM", (995, ZOOM_Y_MIN - 5), (0, 0, 255))

    cv.rectangle(
        image,
        (MAIN_QUEST_X_MIN, MAIN_QUEST_Y_MIN),
        (MAIN_QUEST_X_MAX, MAIN_QUEST_Y_MAX),
        (0, 80, 255),
        2,
    )
    draw_label(image, "NO CLICK: MAIN QUEST", (MAIN_QUEST_X_MIN - 8, MAIN_QUEST_Y_MIN - 8), (0, 80, 255))

    cv.line(image, (0, MAP_TOP), (image.shape[1], MAP_TOP), (160, 160, 160), 1)
    cv.line(image, (0, MAP_BOTTOM), (image.shape[1], MAP_BOTTOM), (160, 160, 160), 1)


def point_status(point: tuple[int, int]) -> str:
    if is_right_zoom_control(point):
        return "zoom_forbidden"
    if is_main_quest_prompt(point):
        return "main_quest_forbidden"
    if is_forbidden_ui_point(point):
        return "ui_forbidden"
    if is_safe_inner_point(point):
        return "clickable_map"
    return "deferred"


def annotate(
    image,
    *,
    target: str | None = None,
    icon_limit: int = 60,
    white_limit: int = 40,
    sample_limit: int = 20,
) -> tuple[object, dict]:
    overlay = image.copy()
    draw_regions(overlay)

    icons = find_icon_candidates(image)[:icon_limit]
    whites = find_white_marker_candidates(image)[:white_limit]

    records: dict = {
        "regions": {
            "safe_click_area": [SAFE_X_MIN, SAFE_Y_MIN, SAFE_X_MAX, SAFE_Y_MAX],
            "zoom_no_click": [ZOOM_X_MIN, ZOOM_Y_MIN, ZOOM_X_MAX, MAP_BOTTOM],
            "main_quest_no_click": [MAIN_QUEST_X_MIN, MAIN_QUEST_Y_MIN, MAIN_QUEST_X_MAX, MAIN_QUEST_Y_MAX],
            "map_y": [MAP_TOP, MAP_BOTTOM],
        },
        "icon_candidates": [],
        "white_candidates": [],
        "target_sample_points": [],
        "target_label_probes": [],
    }

    for index, point in enumerate(icons, 1):
        color = (0, 255, 255) if is_safe_inner_point(point) else (0, 160, 255)
        cv.circle(overlay, point, 8, color, 2)
        draw_label(overlay, f"C{index}", (point[0] + 9, point[1] - 7), color)
        records["icon_candidates"].append(
            {"id": f"C{index}", "point": list(point), "status": point_status(point)}
        )

    for index, point in enumerate(whites, 1):
        color = (255, 255, 255) if is_safe_inner_point(point) else (180, 180, 180)
        cv.circle(overlay, point, 11, color, 2)
        draw_label(overlay, f"W{index}", (point[0] + 10, point[1] + 13), color)
        records["white_candidates"].append(
            {
                "id": f"W{index}",
                "point": list(point),
                "status": "reference_only",
                "note": "white markers include many non-clickable route/status marks",
            }
        )

    if target:
        for index, point in enumerate(city_sample_points(target)[:sample_limit], 1):
            color = (255, 170, 0) if is_safe_inner_point(point) else (130, 90, 0)
            cv.rectangle(
                overlay,
                (point[0] - 8, point[1] - 8),
                (point[0] + 8, point[1] + 8),
                color,
                2,
            )
            draw_label(overlay, f"S{index}", (point[0] + 10, point[1] - 10), color)
            records["target_sample_points"].append(
                {"id": f"S{index}", "point": list(point), "status": point_status(point)}
            )

        for index, probe in enumerate(find_target_label_probes(image, target), 1):
            cv.circle(overlay, probe.label_center, 14, (255, 0, 255), 2)
            draw_label(overlay, f"T{index}:{probe.raw_text}", (probe.label_center[0] + 12, probe.label_center[1] - 12), (255, 0, 255))
            record = {
                "id": f"T{index}",
                "raw_text": probe.raw_text,
                "match_score": probe.match_score,
                "label_center": list(probe.label_center),
                "click_points": [],
            }
            for point in probe.click_points:
                cv.circle(overlay, point, 5, (255, 0, 255), -1)
                record["click_points"].append({"point": list(point), "status": point_status(point)})
            records["target_label_probes"].append(record)

    return overlay, records


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=Path, help="existing screenshot to annotate")
    parser.add_argument("--capture", action="store_true", help="capture current screenshot without clicking")
    parser.add_argument("--target", help="optional target city name for OCR label probe overlay")
    parser.add_argument("--output", type=Path, help="output PNG path")
    parser.add_argument("--json-output", type=Path, help="output JSON path")
    parser.add_argument("--icon-limit", type=int, default=60)
    parser.add_argument("--white-limit", type=int, default=0, help="white reference marker limit; default hides noisy white markers")
    parser.add_argument("--sample-limit", type=int, default=20)
    args = parser.parse_args()

    if not args.capture and not args.image:
        parser.error("Use --image or --capture")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.capture:
        if not connect():
            print("Failed to connect emulator. Check ADB/MuMu settings first.")
            return 1
        image = screenshot_image()
        source = OUT_DIR / f"{timestamp}_capture.png"
        cv.imwrite(str(source), image)
    else:
        source = args.image
        image = cv.imread(str(source))
        if image is None:
            print(f"Failed to read image: {source}")
            return 1

    overlay, records = annotate(
        image,
        target=args.target,
        icon_limit=args.icon_limit,
        white_limit=args.white_limit,
        sample_limit=args.sample_limit,
    )
    records["source_image"] = str(source)

    out_path = args.output or OUT_DIR / f"{timestamp}_candidates.png"
    json_path = args.json_output or out_path.with_suffix(".json")
    cv.imwrite(str(out_path), overlay)
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Overlay: {out_path}")
    print(f"JSON: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
