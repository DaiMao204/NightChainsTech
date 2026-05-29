"""
Build a curated city map sample catalog from refined map row annotations.

The resulting file is an intermediate resource for the 2026 map rewrite. It
stores reliable viewport click samples, not final world coordinates.
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROWS_DIR = PROJECT_ROOT / "diagnostics" / "map_rows"
DEFAULT_OUT = PROJECT_ROOT / "resources" / "map" / "CityMapSamples2026.json"
LEGACY_POS_PATH = PROJECT_ROOT / "resources" / "goods" / "CityPosData.json"

CONFIDENCE_SCORE = {
    "missing": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def load_sample_images(row_dir: Path) -> dict[int, str]:
    samples_path = row_dir / "samples.json"
    if not samples_path.exists():
        return {}

    samples = load_json(samples_path).get("samples", [])
    result = {}
    for sample in samples:
        image = Path(sample["image"])
        result[int(sample["step"])] = relpath(image)
    return result


def edge_warning(point: list[int] | None) -> bool:
    if not point:
        return False
    x, y = point
    return x < 60 or x > 1220 or y < 100 or y > 610


def annotation_score(annotation: dict) -> float:
    score = CONFIDENCE_SCORE.get(annotation.get("refine_confidence"), 0) * 100

    visibility = annotation.get("visibility", "")
    if "edge" in visibility or "occluded" in visibility:
        score -= 55
    if "panel_verified" in visibility:
        score += 60
    if visibility == "auto_probe":
        score += 35

    candidate = annotation.get("candidate") or {}
    marker_type = candidate.get("marker_type")
    if marker_type == "red_hint" and "panel_verified" not in visibility:
        score -= 35
    if edge_warning(annotation.get("refined_point")):
        score -= 25

    distance = candidate.get("distance")
    if isinstance(distance, (int, float)):
        score -= min(distance, 120) / 3

    return round(score, 2)


def sample_from_annotation(row_dir: Path, images: dict[int, str], annotation: dict) -> dict:
    step = int(annotation["step"])
    candidate = annotation.get("candidate") or {}
    click_point = annotation.get("refined_point") or annotation.get("screen_point")
    return {
        "row": row_dir.name,
        "step": step,
        "image": images.get(step),
        "manual_point": annotation.get("screen_point"),
        "click_point": click_point,
        "visibility": annotation.get("visibility"),
        "confidence": annotation.get("refine_confidence"),
        "score": annotation_score(annotation),
        "marker_type": candidate.get("marker_type"),
        "candidate_distance": candidate.get("distance"),
        "candidate_count": annotation.get("candidate_count"),
        "ocr_score": annotation.get("score"),
        "note": annotation.get("note"),
    }


def collect_rows(rows_dir: Path) -> tuple[list[str], dict[str, list[dict]]]:
    rows = []
    by_city = defaultdict(list)

    for refined_path in sorted(rows_dir.glob("*/refined_annotations.json")):
        row_dir = refined_path.parent
        rows.append(row_dir.name)
        images = load_sample_images(row_dir)
        for annotation in load_json(refined_path).get("annotations", []):
            name = annotation.get("name")
            if not name:
                continue
            by_city[name].append(sample_from_annotation(row_dir, images, annotation))

    return rows, by_city


def find_point_conflicts(by_city: dict[str, list[dict]]) -> dict[tuple[str, int, tuple[int, int]], set[str]]:
    point_map = defaultdict(set)
    for city, samples in by_city.items():
        for sample in samples:
            point = sample.get("click_point")
            if point:
                key = (sample["row"], sample["step"], tuple(point))
                point_map[key].add(city)
    return {key: names for key, names in point_map.items() if len(names) > 1}


def review_reasons(best: dict | None, samples: list[dict], conflict_names: list[str]) -> list[str]:
    reasons = []
    if not best:
        return ["no_sample"]

    if best["confidence"] != "high":
        reasons.append("no_high_confidence_sample")
    if "edge" in (best.get("visibility") or ""):
        reasons.append("best_sample_near_viewport_edge")
    if "occluded" in (best.get("visibility") or ""):
        reasons.append("best_sample_occluded")
    if best.get("marker_type") == "red_hint" and "panel_verified" not in (best.get("visibility") or ""):
        reasons.append("best_sample_is_red_marker_or_hint")
    if edge_warning(best.get("click_point")):
        reasons.append("best_click_point_near_screen_edge")
    if conflict_names:
        reasons.append("candidate_point_conflicts_with_" + "_".join(sorted(conflict_names)))
    if all(sample.get("visibility") == "auto_probe" for sample in samples):
        reasons.append("auto_probe_only")
    return reasons


def build_catalog(rows_dir: Path) -> dict:
    source_rows, by_city = collect_rows(rows_dir)
    conflicts = find_point_conflicts(by_city)

    legacy_names = set(load_json(LEGACY_POS_PATH).keys()) if LEGACY_POS_PATH.exists() else set()
    sampled_names = set(by_city.keys())

    cities = {}
    review_required = {}
    for city in sorted(sampled_names):
        samples = sorted(
            by_city[city],
            key=lambda item: (
                item["score"],
                CONFIDENCE_SCORE.get(item.get("confidence"), 0),
            ),
            reverse=True,
        )
        best = samples[0] if samples else None

        conflict_names = []
        if best and best.get("click_point"):
            key = (best["row"], best["step"], tuple(best["click_point"]))
            conflict_names = sorted(name for name in conflicts.get(key, set()) if name != city)

        reasons = review_reasons(best, samples, conflict_names)
        if reasons:
            review_required[city] = reasons

        cities[city] = {
            "best_sample": best,
            "sample_count": len(samples),
            "samples": samples,
        }

    missing_legacy = sorted(legacy_names - sampled_names)
    sample_only = sorted(sampled_names - legacy_names)

    return {
        "schema_version": 1,
        "resolution": [1280, 720],
        "coordinate_space": "viewport_screen_points_after_manual_map_sampling",
        "status": "intermediate_calibration_data_not_final_world_coordinates",
        "source_rows": source_rows,
        "city_count": len(cities),
        "legacy_city_count": len(legacy_names),
        "missing_legacy_cities": missing_legacy,
        "sample_only_cities": sample_only,
        "review_required": review_required,
        "cities": cities,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows-dir", type=Path, default=DEFAULT_ROWS_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    catalog = build_catalog(args.rows_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Saved city map sample catalog: {args.out}")
    print(f"Sampled cities: {catalog['city_count']}")
    if catalog["missing_legacy_cities"]:
        print("Missing legacy cities: " + ", ".join(catalog["missing_legacy_cities"]))
    if catalog["sample_only_cities"]:
        print("Sample-only cities: " + ", ".join(catalog["sample_only_cities"]))
    if catalog["review_required"]:
        print("Review required: " + ", ".join(catalog["review_required"].keys()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
