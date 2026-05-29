from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from loguru import logger

from app.common.runtime_status import emit_run_status
from app.utils.config import CITYS
from auto.run_business.main import go_business
from core.control.control import connect, input_swipe, input_tap, screenshot_image
from core.image.ocr import predict
from core.preset import get_station, go_city, go_home
from core.preset.map_navigation import (
    MapNavigationError,
    open_station_map_from_home,
    select_station_on_map,
)
from core.preset.page_state import capture_page_state
from core.utils.runtime_state import capture_state, ocr_texts
from core.utils.utils import RESOURCES_PATH, read_json

CARGO_CROP_POS1 = (850, 360)
CARGO_CROP_POS2 = (1260, 445)
PROFILE_ENTRY_POINT = (120, 660)
PROFILE_ENTRY_POINTS = ((160, 660), (145, 650), PROFILE_ENTRY_POINT, (36, 682))
PROFILE_MORE_INFO_POINT = (390, 317)
PROFILE_PRESTIGE_EYE_POINT = (362, 410)
PROFILE_PRESTIGE_DIALOG_CROP1 = (700, 245)
PROFILE_PRESTIGE_DIALOG_CROP2 = (1190, 675)
PROFILE_PRESTIGE_DIALOG_CONFIRM_POINT = (950, 645)
PROFILE_PRESTIGE_SCROLL_START = (960, 600)
PROFILE_PRESTIGE_SCROLL_END = (960, 325)
PROFILE_PRESTIGE_SCROLL_ATTEMPTS = 1
PROFILE_PANEL_CLOSE_POINT = (1020, 520)
PRESTIGE_THRESHOLDS_PATH = RESOURCES_PATH / "goods" / "CityPrestigeThresholds2026.json"
CITY_GOODS_PATH = RESOURCES_PATH / "goods" / "CityGoodsSellData.json"
ATTACHED_TO_CITY_PATH = RESOURCES_PATH / "goods" / "AttachedToCityData.json"
PLANNER_MAX_PRESTIGE_LEVEL = 20
PROFILE_PANEL_TEXTS = ("查看更多信息", "运营总览", "导航手册", "UID", "资产")


@dataclass
class AccountProfileResult:
    ok: bool
    city_name: str | None = None
    cargo_capacity: int | None = None
    prestige_by_city: dict[str, int] = field(default_factory=dict)
    prestige_value_by_city: dict[str, int] = field(default_factory=dict)
    unavailable_cities: list[str] | None = None
    error: str | None = None


def _clean_text(text: str) -> str:
    return (
        str(text or "")
        .replace(" ", "")
        .replace(",", "")
        .replace("，", "")
        .replace("：", ":")
    )


def _numbers(text: str) -> list[int]:
    return [int(match.group(0)) for match in re.finditer(r"\d+", _clean_text(text))]


def _numbers_near_city(text: str, city: str) -> list[int]:
    return _numbers(_clean_text(text).replace(city, ""))


@lru_cache(maxsize=1)
def load_prestige_thresholds() -> dict[str, Any]:
    data = read_json(PRESTIGE_THRESHOLDS_PATH, {})
    return data if isinstance(data, dict) else {}


@lru_cache(maxsize=1)
def load_attached_to_city() -> dict[str, str]:
    data = read_json(ATTACHED_TO_CITY_PATH, {})
    if not isinstance(data, dict):
        return {}
    return {str(city): str(master) for city, master in data.items() if str(city).strip()}


def prestige_master_city(city_name: str | None) -> str | None:
    if not city_name:
        return None
    city = str(city_name)
    return load_attached_to_city().get(city, city)


@lru_cache(maxsize=1)
def load_city_names() -> tuple[str, ...]:
    thresholds = load_prestige_thresholds()
    cities = thresholds.get("cities") if isinstance(thresholds, dict) else {}
    names: set[str] = set()
    if isinstance(cities, dict):
        names.update(
            master
            for name in cities.keys()
            if (master := prestige_master_city(str(name).strip()))
        )

    if not names:
        city_goods = read_json(CITY_GOODS_PATH, {})
        if isinstance(city_goods, dict):
            names.update(str(name) for name in city_goods.keys() if str(name).strip())

    return tuple(sorted(names, key=len, reverse=True))


def _threshold_map(city_name: str | None = None) -> dict[int, int]:
    thresholds = load_prestige_thresholds()
    cities = thresholds.get("cities") if isinstance(thresholds, dict) else {}
    raw: dict[str, Any] | None = None
    master_city = prestige_master_city(city_name)
    if master_city and isinstance(cities, dict):
        city_raw = cities.get(master_city)
        if isinstance(city_raw, dict) and len(city_raw) >= 3:
            raw = city_raw
    if raw is None:
        raw = thresholds.get("default") if isinstance(thresholds, dict) else {}
    if not isinstance(raw, dict):
        return {}
    result: dict[int, int] = {}
    for level, value in raw.items():
        try:
            result[int(level)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def prestige_value_to_level(
    prestige_value: int,
    city_name: str | None = None,
    *,
    max_level: int = PLANNER_MAX_PRESTIGE_LEVEL,
) -> int | None:
    """Convert raw city reputation value to the planner prestige level."""
    thresholds = _threshold_map(city_name)
    if not thresholds:
        return None

    level = 1
    for candidate_level, required_value in sorted(thresholds.items()):
        if candidate_level > max_level:
            continue
        if prestige_value >= required_value:
            level = candidate_level
        else:
            break
    return level


def parse_cargo_capacity(texts: list[str]) -> int | None:
    """Parse the max cargo number from OCR texts such as 13/545."""
    candidates: list[int] = []
    for text in texts:
        clean = _clean_text(text)
        for match in re.finditer(r"(\d+)\s*/\s*(\d+)", clean):
            candidates.append(int(match.group(2)))
    return max(candidates) if candidates else None


def parse_prestige_level(texts: list[str]) -> int | None:
    """Parse a direct city prestige level from OCR around the city page."""
    cleaned = [_clean_text(text) for text in texts if str(text).strip()]
    joined = "".join(cleaned)
    for pattern in (
        r"声望等级(?:Lv\.?|等级)?(\d{1,2})",
        r"声望(?:等级)?(?:Lv\.?)?(\d{1,2})",
    ):
        match = re.search(pattern, joined, re.I)
        if match:
            return max(1, min(int(match.group(1)), PLANNER_MAX_PRESTIGE_LEVEL))

    for index, text in enumerate(cleaned):
        if "声望" not in text:
            continue
        nearby = "".join(cleaned[index : index + 4])
        match = re.search(r"(?:Lv\.?)?(\d{1,2})", nearby, re.I)
        if match:
            return max(1, min(int(match.group(1)), PLANNER_MAX_PRESTIGE_LEVEL))
    return None


def _entry_center(entry: dict[str, Any]) -> tuple[float, float]:
    position = entry.get("position") or []
    if not position:
        return 0.0, 0.0
    xs = [float(point[0]) for point in position if len(point) >= 2]
    ys = [float(point[1]) for point in position if len(point) >= 2]
    if not xs or not ys:
        return 0.0, 0.0
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _entry_bounds(entry: dict[str, Any]) -> tuple[float, float, float, float]:
    position = entry.get("position") or []
    xs = [float(point[0]) for point in position if len(point) >= 2]
    ys = [float(point[1]) for point in position if len(point) >= 2]
    if not xs or not ys:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def _looks_like_prestige_value(value: int) -> bool:
    return 0 <= value <= 999999


def parse_city_prestige_values_from_entries(
    entries: list[dict[str, Any]],
    city_names: tuple[str, ...] | None = None,
) -> dict[str, int]:
    """Parse raw city reputation values from positioned OCR results."""
    city_names = city_names or load_city_names()
    cleaned_entries: list[tuple[str, float, float, dict[str, Any]]] = []
    for entry in entries:
        text = _clean_text(entry.get("text", ""))
        if not text:
            continue
        x, y = _entry_center(entry)
        cleaned_entries.append((text, x, y, entry))

    result: dict[str, int] = {}
    for city in city_names:
        city_entry = next(
            ((text, x, y, entry) for text, x, y, entry in cleaned_entries if city in text),
            None,
        )
        if city_entry is None:
            continue

        city_text, city_x, city_y, _ = city_entry
        candidates: list[int] = [
            value
            for value in _numbers_near_city(city_text, city)
            if _looks_like_prestige_value(value)
        ]
        for text, x, y, _ in cleaned_entries:
            if abs(y - city_y) > 36:
                continue
            if x < city_x - 20:
                continue
            candidates.extend(
                value for value in _numbers(text) if _looks_like_prestige_value(value)
            )
        if candidates:
            result[city] = max(candidates)

    return result


def parse_city_prestige_values(
    texts: list[str],
    city_names: tuple[str, ...] | None = None,
) -> dict[str, int]:
    """Fallback parser for OCR text-only results."""
    city_names = city_names or load_city_names()
    cleaned = [_clean_text(text) for text in texts if str(text).strip()]
    result: dict[str, int] = {}
    for city in city_names:
        for index, text in enumerate(cleaned):
            if city not in text:
                continue
            candidates: list[int] = []
            for piece in cleaned[index : index + 5]:
                if piece != text and any(
                    other_city != city and other_city in piece
                    for other_city in city_names
                ):
                    break
                candidates.extend(
                    value
                    for value in _numbers_near_city(piece, city)
                    if _looks_like_prestige_value(value)
                )
            if candidates:
                result[city] = max(candidates)
                break
    return result


def prestige_values_to_levels(values_by_city: dict[str, int]) -> dict[str, int]:
    levels: dict[str, int] = {}
    for city, prestige_value in values_by_city.items():
        level = prestige_value_to_level(prestige_value, city)
        if level is not None:
            levels[city] = level
    return levels


def _tap_ocr_text(
    texts: tuple[str, ...],
    *,
    fallback: tuple[int, int] | None = None,
    cropped_pos1: tuple[int, int] = (0, 0),
    cropped_pos2: tuple[int, int] = (0, 0),
) -> bool:
    raw = screenshot_image()
    for entry in predict(raw, cropped_pos1=cropped_pos1, cropped_pos2=cropped_pos2):
        entry_text = _clean_text(entry.get("text", ""))
        if not any(text in entry_text for text in texts):
            continue
        x, y = _entry_center(entry)
        input_tap((int(x), int(y)))
        return True
    if fallback:
        input_tap(fallback)
        return True
    return False


def _screen_texts(
    cropped_pos1: tuple[int, int] = (0, 0),
    cropped_pos2: tuple[int, int] = (0, 0),
) -> list[str]:
    raw = screenshot_image()
    return [
        _clean_text(entry.get("text", ""))
        for entry in predict(raw, cropped_pos1=cropped_pos1, cropped_pos2=cropped_pos2)
        if _clean_text(entry.get("text", ""))
    ]


def _has_any_text(texts: list[str], needles: tuple[str, ...]) -> bool:
    return any(needle in text for text in texts for needle in needles)


def _is_profile_panel_open() -> bool:
    return _has_any_text(_screen_texts(), PROFILE_PANEL_TEXTS)


def _open_profile_panel() -> bool:
    go_home()
    time.sleep(0.5)
    for point in PROFILE_ENTRY_POINTS:
        input_tap(point)
        time.sleep(1.0)
        if _is_profile_panel_open():
            return True
    capture_state("account_profile_panel_missing")
    capture_page_state("account_profile_panel_missing")
    return False


def _tap_prestige_eye() -> bool:
    raw = screenshot_image()
    entries = predict(raw)
    prestige_entry: dict[str, Any] | None = None
    for entry in entries:
        if "声望总和" not in _clean_text(entry.get("text", "")):
            continue
        prestige_entry = entry
        break

    if prestige_entry is not None:
        label_x, label_y = _entry_center(prestige_entry)
        same_row_entries: list[tuple[float, float, dict[str, Any]]] = []
        for entry in entries:
            text = _clean_text(entry.get("text", ""))
            if not any(ch.isdigit() for ch in text):
                continue
            x, y = _entry_center(entry)
            if x <= label_x or abs(y - label_y) > 28:
                continue
            same_row_entries.append((x, y, entry))
        if same_row_entries:
            _, y, value_entry = min(same_row_entries, key=lambda item: item[0])
            _, _, max_x, _ = _entry_bounds(value_entry)
            input_tap((int(max_x - 14), int(y)))
            return True

        input_tap((int(label_x + 175), int(label_y)))
        return True

    input_tap(PROFILE_PRESTIGE_EYE_POINT)
    return True


def _prestige_dialog_entries() -> list[dict[str, Any]]:
    raw = screenshot_image()
    return predict(
        raw,
        cropped_pos1=PROFILE_PRESTIGE_DIALOG_CROP1,
        cropped_pos2=PROFILE_PRESTIGE_DIALOG_CROP2,
    )


def _is_prestige_dialog_open() -> bool:
    entries = _prestige_dialog_entries()
    texts = [_clean_text(entry.get("text", "")) for entry in entries]
    return any("所有城市声望" in text for text in texts) or bool(
        parse_city_prestige_values_from_entries(entries)
    )


def open_profile_prestige_dialog() -> bool:
    emit_run_status("正在读取账号配置", "正在打开个人资料")
    if not _open_profile_panel():
        return False

    if not _tap_ocr_text(("查看更多信息",), fallback=PROFILE_MORE_INFO_POINT):
        capture_state("account_profile_more_info_missing")
        capture_page_state("account_profile_more_info_missing")
        return False

    time.sleep(0.8)
    for _ in range(2):
        emit_run_status("正在读取城市声望", "正在打开所有城市声望列表")
        _tap_prestige_eye()
        time.sleep(0.8)
        if _is_prestige_dialog_open():
            return True

    capture_state("account_profile_prestige_dialog_missing")
    capture_page_state("account_profile_prestige_dialog_missing")
    return False


def close_profile_prestige_dialog() -> None:
    input_tap(PROFILE_PRESTIGE_DIALOG_CONFIRM_POINT)
    time.sleep(0.4)
    input_tap(PROFILE_PANEL_CLOSE_POINT)
    time.sleep(0.5)


def reset_profile_prestige_scroll() -> None:
    return None


def read_profile_city_prestige() -> tuple[dict[str, int], dict[str, int]]:
    """Open profile details and parse every city prestige from the prestige dialog."""
    emit_run_status("正在读取城市声望", "正在进入个人资料声望列表")
    if not open_profile_prestige_dialog():
        go_home()
        return {}, {}

    reset_profile_prestige_scroll()
    values: dict[str, int] = {}
    stale_scrolls = 0
    last_count = 0
    entries: list[dict[str, Any]] = []
    for attempt in range(PROFILE_PRESTIGE_SCROLL_ATTEMPTS + 1):
        entries = _prestige_dialog_entries()
        page_values = parse_city_prestige_values_from_entries(entries)
        if not page_values:
            page_values = parse_city_prestige_values(
                [entry.get("text", "") for entry in entries]
            )
        values.update(page_values)
        if len(values) == last_count:
            stale_scrolls += 1
        else:
            stale_scrolls = 0
            last_count = len(values)
        if stale_scrolls >= 2:
            break
        if attempt < PROFILE_PRESTIGE_SCROLL_ATTEMPTS:
            emit_run_status(
                "正在读取城市声望",
                f"已识别 {len(values)} 个城市，继续滑动读取",
            )
            input_swipe(
                PROFILE_PRESTIGE_SCROLL_START,
                PROFILE_PRESTIGE_SCROLL_END,
                swipe_time=700,
            )
            time.sleep(0.8)

    if not values:
        raw = screenshot_image()
        capture_state(
            "account_profile_city_prestige_missing",
            raw,
            extra={"texts": [entry.get("text", "") for entry in entries[:80]]},
        )
        capture_page_state(
            "account_profile_city_prestige_missing",
            extra={"texts": [entry.get("text", "") for entry in entries[:80]]},
        )

    close_profile_prestige_dialog()
    emit_run_status("城市声望读取完成", f"已识别 {len(values)} 个城市声望")
    return values, prestige_values_to_levels(values)


def read_current_city_prestige(city_name: str) -> int | None:
    if not go_city():
        capture_state("account_profile_go_city_failed", extra={"city": city_name})
        capture_page_state("account_profile_go_city_failed", extra={"city": city_name})
        return None
    texts = ocr_texts()
    level = parse_prestige_level(texts)
    if level is None:
        capture_state(
            "account_profile_prestige_missing",
            extra={"city": city_name, "texts": texts[:40]},
        )
        capture_page_state(
            "account_profile_prestige_missing",
            extra={"city": city_name, "texts": texts[:40]},
        )
    return level


def read_cargo_capacity() -> int | None:
    emit_run_status("正在读取货舱", "正在进入交易所读取货舱上限")
    if not go_business("buy"):
        capture_state("account_profile_buy_page_failed")
        capture_page_state("account_profile_buy_page_failed")
        return None
    texts = ocr_texts(cropped_pos1=CARGO_CROP_POS1, cropped_pos2=CARGO_CROP_POS2)
    capacity = parse_cargo_capacity(texts)
    if capacity is None:
        all_texts = ocr_texts()
        capacity = parse_cargo_capacity(all_texts)
        if capacity is None:
            capture_state(
                "account_profile_cargo_missing",
                extra={"texts": texts[:20], "all_texts": all_texts[:40]},
            )
            capture_page_state(
                "account_profile_cargo_missing",
                extra={"texts": texts[:20], "all_texts": all_texts[:40]},
            )
    return capacity


def read_unavailable_map_cities(cities: list[str] | None = None) -> list[str] | None:
    """Open the route map and identify cities whose panel says they are unopened."""
    target_cities = [city for city in (cities or CITYS) if city]
    if not target_cities:
        return []

    emit_run_status("正在读取城市开放状态", "正在打开站点地图")
    if not go_home():
        capture_state("account_profile_unavailable_go_home_failed")
        capture_page_state("account_profile_unavailable_go_home_failed")
        return None

    open_station_map_from_home()
    unavailable: list[str] = []
    for index, city in enumerate(target_cities, start=1):
        emit_run_status(
            "正在读取城市开放状态",
            f"正在检查 {city}（{index}/{len(target_cities)}）",
            target_city=city,
        )
        try:
            probe = select_station_on_map(
                city,
                travel=False,
                reset_first=True,
                coordinate_first=True,
                route_first=True,
                fallback_scan=False,
            )
        except MapNavigationError as exc:
            logger.warning(f"检查城市开放状态失败: {city} {exc}")
            continue
        except Exception as exc:
            logger.exception(f"检查城市开放状态异常: {city} {exc}")
            continue

        if not probe:
            logger.warning(f"未能确认城市开放状态: {city}")
            continue
        panel = probe.panel
        if panel.unavailable or (
            not panel.has_travel_button and not panel.has_current_station_actions
        ):
            unavailable.append(city)

    go_home()
    emit_run_status("城市开放状态读取完成", f"未开放城市 {len(unavailable)} 个")
    return unavailable


def analyze_account_profile() -> AccountProfileResult:
    logger.info("开始读取账号配置")
    emit_run_status("正在读取账号配置", "正在连接游戏")
    if not connect():
        return AccountProfileResult(False, error="ADB连接失败")
    try:
        city_name = get_station()
    except Exception as exc:
        logger.exception("识别当前城市失败")
        return AccountProfileResult(False, error=f"识别当前城市失败: {exc}")

    emit_run_status("正在读取账号配置", f"当前城市：{city_name}", current_city=city_name)
    value_by_city, prestige_by_city = read_profile_city_prestige()
    if city_name not in prestige_by_city:
        current_level = read_current_city_prestige(city_name)
        if current_level is not None:
            prestige_by_city[city_name] = current_level

    cargo_capacity = read_cargo_capacity()
    unavailable_cities = read_unavailable_map_cities()
    go_home()

    if not prestige_by_city and cargo_capacity is None:
        return AccountProfileResult(
            False,
            city_name=city_name,
            cargo_capacity=None,
            prestige_by_city={},
            prestige_value_by_city={},
            unavailable_cities=unavailable_cities,
            error="未能识别城市声望和货舱上限",
        )

    logger.info(
        "账号配置读取完成: city={} prestige_cities={} cargo={}",
        city_name,
        len(prestige_by_city),
        cargo_capacity if cargo_capacity is not None else "未知",
    )
    return AccountProfileResult(
        True,
        city_name=city_name,
        cargo_capacity=cargo_capacity,
        prestige_by_city=prestige_by_city,
        prestige_value_by_city=value_by_city,
        unavailable_cities=unavailable_cities,
    )
