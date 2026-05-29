from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import cv2 as cv
from loguru import logger

from core.control.control import screenshot_image
from core.image.ocr import predict
from core.utils.utils import ROOT_PATH


STATE_DIR = ROOT_PATH / "diagnostics" / "runtime_state"


def _safe_label(label: str) -> str:
    label = re.sub(r"[^0-9A-Za-z_.-]+", "_", label.strip())
    return label.strip("_") or "state"


def _raw_image(image: Any | None = None):
    if image is None:
        return screenshot_image()
    if hasattr(image, "image"):
        return image.image
    return image


def ocr_texts(
    image: Any | None = None,
    *,
    cropped_pos1: tuple[int, int] = (0, 0),
    cropped_pos2: tuple[int, int] = (0, 0),
) -> list[str]:
    raw = _raw_image(image)
    try:
        return [
            item.get("text", "").replace(" ", "")
            for item in predict(raw, cropped_pos1=cropped_pos1, cropped_pos2=cropped_pos2)
        ]
    except Exception as exc:
        logger.debug(f"OCR 状态读取失败: {exc}")
        return []


def has_any_text(texts: list[str], needles: tuple[str, ...]) -> bool:
    return any(needle in text for text in texts for needle in needles)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def capture_state(
    label: str,
    image: Any | None = None,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = _raw_image(image)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{time.strftime('%Y%m%d_%H%M%S')}_{_safe_label(label)}"
    image_path = STATE_DIR / f"{stem}.png"
    json_path = STATE_DIR / f"{stem}.json"

    cv.imwrite(str(image_path), raw)
    texts = ocr_texts(raw)
    data = {
        "label": label,
        "image": str(image_path.resolve()),
        "ocr_texts": texts,
        "extra": _json_safe(extra or {}),
    }
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.warning(f"已保存页面状态: {image_path.resolve()}")
    return data
