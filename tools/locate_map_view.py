"""
Locate a station-map screenshot in HomeStationFactory world coordinates.

This is a no-click prototype. It detects colored station marker candidates in a
screenshot, then fits them to the known minimap coordinates from
resources/map/CityWorld2026.json using a constrained transform:

    screen_x = scale * world_x + tx
    screen_y = -scale * world_y + ty

The map background is ignored because it is animated/noisy.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2 as cv
import numpy as np

from detect_map_anchors import detect_city_icons


PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORLD_PATH = PROJECT_ROOT / "resources" / "map" / "CityWorld2026.json"
OUT_DIR = PROJECT_ROOT / "diagnostics" / "map_locator"


def load_world_stations() -> list[dict]:
    data = json.loads(WORLD_PATH.read_text(encoding="utf-8"))
    return data["stations"]


def project(station: dict, scale: float, tx: float, ty: float) -> tuple[float, float]:
    return scale * station["x"] + tx, -scale * station["y"] + ty


def nearest_candidate(point: tuple[float, float], candidates: list[tuple[int, int]]) -> tuple[tuple[int, int], float] | None:
    if not candidates:
        return None
    px, py = point
    best = min(candidates, key=lambda item: (item[0] - px) ** 2 + (item[1] - py) ** 2)
    distance = math.hypot(best[0] - px, best[1] - py)
    return best, distance


def score_transform(
    stations: list[dict],
    candidates: list[tuple[int, int]],
    scale: float,
    tx: float,
    ty: float,
    threshold: float,
) -> tuple[float, list[dict]]:
    used_candidates: set[tuple[int, int]] = set()
    matches: list[dict] = []
    for station in stations:
        sx, sy = project(station, scale, tx, ty)
        if sx < -60 or sx > 1340 or sy < 40 or sy > 760:
            continue
        nearest = nearest_candidate((sx, sy), candidates)
        if not nearest:
            continue
        candidate, distance = nearest
        if distance > threshold or candidate in used_candidates:
            continue
        used_candidates.add(candidate)
        matches.append(
            {
                "name": station["name"],
                "world": [station["x"], station["y"]],
                "projected": [round(sx, 2), round(sy, 2)],
                "candidate": list(candidate),
                "distance": round(distance, 2),
            }
        )

    if not matches:
        return -1e9, matches

    mean_error = sum(item["distance"] for item in matches) / len(matches)
    score = len(matches) * 100 - mean_error * 3
    if len(matches) >= 3:
        score += 80
    if len(matches) >= 5:
        score += 160
    return score, matches


def locate_view(
    stations: list[dict],
    candidates: list[tuple[int, int]],
    *,
    scale_min: float = 0.28,
    scale_max: float = 0.38,
    scale_step: float = 0.0025,
    threshold: float = 28.0,
) -> dict | None:
    best: dict | None = None
    scales = np.arange(scale_min, scale_max + scale_step / 2, scale_step)
    for candidate in candidates:
        cx, cy = candidate
        for station in stations:
            for scale in scales:
                tx = cx - scale * station["x"]
                ty = cy + scale * station["y"]
                score, matches = score_transform(stations, candidates, float(scale), tx, ty, threshold)
                if best is None or score > best["score"]:
                    best = {
                        "score": round(score, 3),
                        "scale": round(float(scale), 5),
                        "tx": round(float(tx), 3),
                        "ty": round(float(ty), 3),
                        "match_count": len(matches),
                        "mean_error": round(
                            sum(item["distance"] for item in matches) / len(matches),
                            3,
                        )
                        if matches
                        else None,
                        "matches": matches,
                    }
    return best


def draw_overlay(image: np.ndarray, candidates: list[tuple[int, int]], stations: list[dict], result: dict | None) -> np.ndarray:
    overlay = image.copy()
    for point in candidates:
        cv.circle(overlay, point, 8, (0, 165, 255), 2, cv.LINE_AA)

    if result:
        scale = result["scale"]
        tx = result["tx"]
        ty = result["ty"]
        matched_names = {item["name"] for item in result["matches"]}
        for station in stations:
            sx, sy = project(station, scale, tx, ty)
            if not (-60 <= sx <= 1340 and 40 <= sy <= 760):
                continue
            color = (0, 255, 0) if station["name"] in matched_names else (180, 180, 180)
            center = (int(round(sx)), int(round(sy)))
            cv.drawMarker(overlay, center, color, markerType=cv.MARKER_CROSS, markerSize=18, thickness=2)
            cv.putText(
                overlay,
                station["name"],
                (center[0] + 8, center[1] - 8),
                cv.FONT_HERSHEY_SIMPLEX,
                0.45,
                color,
                1,
                cv.LINE_AA,
            )

    return overlay


def relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def process_image(path: Path, out_dir: Path, threshold: float) -> dict:
    image = cv.imread(str(path))
    if image is None:
        raise FileNotFoundError(path)

    stations = load_world_stations()
    candidates = [tuple(anchor["center"]) for anchor in detect_city_icons(image)]
    result = locate_view(stations, candidates, threshold=threshold)

    try:
        stem = "__".join(path.resolve().relative_to(PROJECT_ROOT).with_suffix("").parts)
    except ValueError:
        stem = path.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = out_dir / f"{stem}_locator.png"
    json_path = out_dir / f"{stem}_locator.json"
    cv.imwrite(str(overlay_path), draw_overlay(image, candidates, stations, result))

    data = {
        "image": relpath(path),
        "overlay": relpath(overlay_path),
        "candidate_count": len(candidates),
        "candidates": [list(point) for point in candidates],
        "result": result,
    }
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data | {"json": relpath(json_path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--threshold", type=float, default=28.0)
    args = parser.parse_args()

    summaries = []
    for image_path in args.images:
        summary = process_image(image_path, args.out_dir, args.threshold)
        result = summary["result"] or {}
        summaries.append(summary)
        print(
            f"{image_path}: candidates={summary['candidate_count']} "
            f"matches={result.get('match_count')} scale={result.get('scale')} "
            f"mean_error={result.get('mean_error')} score={result.get('score')}"
        )
        if result.get("matches"):
            print("  " + ", ".join(match["name"] for match in result["matches"]))

    index_path = args.out_dir / "index.json"
    index_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"index={index_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
