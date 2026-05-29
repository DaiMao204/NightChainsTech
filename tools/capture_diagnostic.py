"""
Capture a screenshot and optional OCR/point diagnostics from the configured emulator.

Examples:
    python tools/capture_diagnostic.py --label main_map
    python tools/capture_diagnostic.py --label exchange --ocr --point 1176,461
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import cv2 as cv
import onnxruntime as ort

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from core.control.control import connect, screenshot_image
from core.model import app


CAPTURE_DIR = project_root / "diagnostics" / "captures"


def parse_point(value: str) -> tuple[int, int]:
    try:
        x, y = value.split(",", 1)
        return int(x), int(y)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("point must use x,y format") from exc


def safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "capture"


def sample_points(image, points: list[tuple[int, int]]) -> list[dict]:
    hsv_image = cv.cvtColor(image, cv.COLOR_BGR2HSV)
    height, width = image.shape[:2]
    samples = []
    for x, y in points:
        if x < 0 or y < 0 or x >= width or y >= height:
            samples.append({"point": [x, y], "error": "out_of_bounds"})
            continue
        bgr = image[y, x].tolist()
        hsv = hsv_image[y, x].tolist()
        samples.append({"point": [x, y], "bgr": bgr, "hsv": hsv})
    return samples


def run_ocr(image) -> list[dict]:
    from core.image.ocr import predict

    return predict(image, no_crop=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="capture", help="name prefix for saved files")
    parser.add_argument("--ocr", action="store_true", help="include OCR result")
    parser.add_argument(
        "--point",
        action="append",
        type=parse_point,
        default=[],
        help="sample point in x,y format; can be repeated",
    )
    args = parser.parse_args()

    if not connect():
        print("Failed to connect emulator. Check ADB/MuMu settings first.")
        return 1

    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    label = safe_label(args.label)
    image_path = CAPTURE_DIR / f"{timestamp}_{label}.png"
    json_path = CAPTURE_DIR / f"{timestamp}_{label}.json"

    image = screenshot_image()
    cv.imwrite(str(image_path), image)

    height, width = image.shape[:2]
    data = {
        "label": args.label,
        "timestamp": timestamp,
        "image": str(image_path),
        "resolution": {"width": width, "height": height},
        "onnxruntime_providers": ort.get_available_providers(),
        "device": app.Global.device.to_dict(),
        "points": sample_points(image, args.point),
    }
    if args.ocr:
        data["ocr"] = run_ocr(image)

    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved image: {image_path}")
    print(f"Saved data:  {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
