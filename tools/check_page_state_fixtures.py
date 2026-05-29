from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import cv2 as cv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.control.control import screenshot_image
from core.control.control import connect
from core.preset.page_state import PageKind, classify_page

DEFAULT_FIXTURES_DIR = PROJECT_ROOT / "diagnostics" / "page_state_fixtures"
DEFAULT_MANIFEST = DEFAULT_FIXTURES_DIR / "manifest.json"


def load_manifest(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("cases", [])
    if not isinstance(payload, list):
        raise ValueError(f"manifest must be a list or an object with cases: {path}")
    return [case for case in payload if isinstance(case, dict)]


def write_manifest(path: Path, cases: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_image_path(manifest_path: Path, image_path: str) -> Path:
    path = Path(image_path)
    if path.is_absolute():
        return path
    return manifest_path.parent / path


def check_case(manifest_path: Path, case: dict[str, Any]) -> dict[str, Any]:
    image_path = resolve_image_path(manifest_path, str(case.get("image", "")))
    expected = str(case.get("expected", "")).strip()
    min_confidence = float(case.get("min_confidence", 0.7))

    raw = cv.imread(str(image_path))
    if raw is None:
        return {
            "ok": False,
            "image": str(image_path),
            "expected": expected,
            "error": "image not found or unreadable",
        }

    state = classify_page(raw)
    actual = state.kind.value
    ok = actual == expected and state.confidence >= min_confidence
    return {
        "ok": ok,
        "image": str(image_path),
        "expected": expected,
        "actual": actual,
        "confidence": state.confidence,
        "min_confidence": min_confidence,
        "reason": state.reason,
        "matched_texts": state.matched_texts,
        "scores": state.scores,
    }


def classify_image_file(image_path: Path) -> dict[str, Any]:
    raw = cv.imread(str(image_path))
    if raw is None:
        return {
            "ok": False,
            "image": str(image_path),
            "error": "image not found or unreadable",
        }

    state = classify_page(raw)
    return {
        "ok": True,
        "image": str(image_path),
        "actual": state.kind.value,
        "confidence": state.confidence,
        "reason": state.reason,
        "matched_texts": state.matched_texts,
        "scores": state.scores,
    }


def capture_fixture(manifest_path: Path, expected: str, label: str, min_confidence: float) -> dict[str, Any]:
    try:
        PageKind(expected)
    except ValueError as exc:
        valid = ", ".join(kind.value for kind in PageKind)
        raise ValueError(f"unknown expected page kind: {expected}. valid values: {valid}") from exc

    if not connect():
        return {
            "ok": False,
            "error": "connect failed",
            "expected": expected,
            "label": label,
        }

    raw = screenshot_image()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in label).strip("_") or expected
    image_name = f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_label}.png"
    image_path = manifest_path.parent / image_name
    cv.imwrite(str(image_path), raw)

    case = {
        "image": image_name,
        "expected": expected,
        "min_confidence": min_confidence,
        "label": label,
    }
    cases = load_manifest(manifest_path)
    cases.append(case)
    write_manifest(manifest_path, cases)
    state = classify_page(raw)
    return {
        "ok": True,
        "image": str(image_path),
        "case": case,
        "classified": asdict(state),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check page-state classifier against screenshot fixtures.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--capture", choices=[kind.value for kind in PageKind], help="Capture current screen as an expected page kind.")
    parser.add_argument("--label", default="", help="Capture label used in the screenshot filename and manifest.")
    parser.add_argument("--min-confidence", type=float, default=0.7)
    parser.add_argument("--image", help="Classify one screenshot without reading the manifest.")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)

    if args.capture:
        result = capture_fixture(manifest_path, args.capture, args.label or args.capture, args.min_confidence)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.image:
        result = classify_image_file(Path(args.image))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    cases = load_manifest(manifest_path)
    results = [check_case(manifest_path, case) for case in cases]
    ok = all(result["ok"] for result in results)
    print(
        json.dumps(
            {
                "ok": ok,
                "manifest": str(manifest_path),
                "count": len(results),
                "failed": sum(1 for result in results if not result["ok"]),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
