"""
Refine rough manual map annotations into likely icon center points.

The manual annotations identify a city region. This script searches near each
rough point in the corresponding screenshot for saturated map icons and writes
refined points with a confidence label.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import cv2 as cv
import numpy as np

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))


def load_row_samples(row_dir: Path) -> dict[int, Path]:
    samples = json.loads((row_dir / "samples.json").read_text(encoding="utf-8"))
    return {item["step"]: Path(item["image"]) for item in samples["samples"]}


def classify_hue(hue: float) -> str:
    if hue < 10 or hue >= 170:
        return "red_hint"
    if 10 <= hue <= 45:
        return "yellow_or_orange_icon"
    if 80 <= hue <= 110:
        return "cyan_or_blue_icon"
    if 120 <= hue <= 160:
        return "purple_icon"
    return "other_colored_marker"


def find_icon_centers(image, rough: tuple[int, int], radius: int) -> list[dict]:
    x, y = rough
    height, width = image.shape[:2]
    x1, x2 = max(0, x - radius), min(width, x + radius)
    y1, y2 = max(90, y - radius), min(620, y + radius)
    if x1 >= x2 or y1 >= y2:
        return []

    roi = image[y1:y2, x1:x2]
    hsv = cv.cvtColor(roi, cv.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 120)).astype("uint8") * 255
    count, labels, stats, centers = cv.connectedComponentsWithStats(mask)

    results = []
    for index in range(1, count):
        bx, by, bw, bh, area = stats[index]
        if not (20 <= area <= 800 and 4 <= bw <= 42 and 4 <= bh <= 42):
            continue
        cx, cy = centers[index]
        component_mask = labels == index
        mean_hue = float(np.mean(hsv[:, :, 0][component_mask]))
        marker_type = classify_hue(mean_hue)
        point = (int(round(x1 + cx)), int(round(y1 + cy)))
        distance = math.dist(point, rough)
        results.append(
            {
                "point": list(point),
                "distance": round(distance, 2),
                "area": int(area),
                "mean_hue": round(mean_hue, 2),
                "marker_type": marker_type,
                "box": [int(x1 + bx), int(y1 + by), int(bw), int(bh)],
            }
        )
    return sorted(
        results,
        key=lambda item: (
            item["marker_type"] == "red_hint",
            item["distance"],
            -item["area"],
        ),
    )


def confidence(annotation: dict, candidate: dict | None, radius: int) -> str:
    if candidate is None:
        return "missing"
    visibility = annotation.get("visibility", "")
    if "edge" in visibility or "occluded" in visibility:
        return "low"
    if candidate["distance"] > radius * 0.65:
        return "low"
    if candidate["distance"] > radius * 0.35:
        return "medium"
    return "high"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("row_dir", type=Path)
    parser.add_argument("--radius", type=int, default=90)
    args = parser.parse_args()

    annotation_path = args.row_dir / "manual_annotations.json"
    annotations = json.loads(annotation_path.read_text(encoding="utf-8"))
    images = load_row_samples(args.row_dir)

    refined = []
    for annotation in annotations["annotations"]:
        step = annotation["step"]
        image = cv.imread(str(images[step]))
        candidates = find_icon_centers(image, tuple(annotation["screen_point"]), args.radius)
        best = candidates[0] if candidates else None
        refined.append(
            {
                **annotation,
                "refined_point": best["point"] if best else None,
                "refine_confidence": confidence(annotation, best, args.radius),
                "candidate": best,
                "candidate_count": len(candidates),
            }
        )

    out = {
        "source": str(annotation_path),
        "radius": args.radius,
        "annotations": refined,
    }
    out_path = args.row_dir / "refined_annotations.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    for item in refined:
        print(
            f"step_{item['step']:02d} {item['name']}: "
            f"{item['screen_point']} -> {item['refined_point']} "
            f"({item['refine_confidence']})"
        )
    print(f"Saved refined annotations: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
