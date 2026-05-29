from __future__ import annotations

import json
import sys
import argparse
from dataclasses import asdict
from pathlib import Path

import cv2 as cv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.control.control import connect
from core.preset.page_state import capture_page_state, classify_page


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose the current or saved game page.")
    parser.add_argument("image", nargs="?", help="Optional saved screenshot path.")
    args = parser.parse_args()

    if args.image:
        image = cv.imread(args.image)
        if image is None:
            print(json.dumps({"ok": False, "error": f"cannot read image: {args.image}"}, ensure_ascii=False))
            return 1
        state = classify_page(image)
        print(json.dumps({"ok": True, "state": asdict(state)}, ensure_ascii=False, indent=2))
        return 0

    if not connect():
        print(json.dumps({"ok": False, "error": "connect failed"}, ensure_ascii=False))
        return 1
    state = capture_page_state("manual_diagnose")
    print(json.dumps({"ok": True, "state": asdict(state)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
