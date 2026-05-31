"""
Modern station map navigation for the current large map UI.

The old map flow relied on one relative drag and station image templates. The
current map is larger and needs candidate scanning plus right-side panel
verification.
"""

from __future__ import annotations

import difflib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import cv2 as cv
from loguru import logger

import core.control.control as control_state
from core.control.control import input_swipe, input_tap, screenshot_image, wait_stopped
from core.image.ocr import predict
from core.utils.utils import RESOURCES_PATH

from .control import click_image
from .map_locator import locate_map_view, project_station, station_by_name


CITY_SAMPLE_PATH = RESOURCES_PATH / "map" / "CityMapSamples2026.json"
MAP_TOP = 90
MAP_BOTTOM = 705
EDGE_X_MARGIN = 72
EDGE_Y_MARGIN = 34
SCREEN_WIDTH = 1280
SAFE_X_MIN = 0
SAFE_X_MAX = 1279
SAFE_Y_MIN = MAP_TOP
SAFE_Y_MAX = MAP_BOTTOM
ZOOM_X_MIN = 1120
ZOOM_X_MAX = 1185
ZOOM_Y_MIN = 320
MAIN_QUEST_X_MIN = 850
MAIN_QUEST_X_MAX = 1225
MAIN_QUEST_Y_MIN = 625
MAIN_QUEST_Y_MAX = 705
MAP_BACK_BUTTON = (82, 42)
CITY_DEPART_BUTTON = (1201, 666)
NAV_TARGET_X_MIN = 140
NAV_TARGET_X_MAX = 1040
NAV_TARGET_Y_MIN = 140
NAV_TARGET_Y_MAX = 585
NAV_TARGET_CENTER_X = (NAV_TARGET_X_MIN + NAV_TARGET_X_MAX) // 2
NAV_TARGET_CENTER_Y = (NAV_TARGET_Y_MIN + NAV_TARGET_Y_MAX) // 2
MIN_COORDINATE_DRAG_DISTANCE = 120
MAX_COORDINATE_DRAG_DISTANCE = 340


@dataclass
class CityPanel:
    name: str
    raw_name: str
    name_match_score: float
    score: float
    position: list[list[float]]
    has_travel_button: bool = False
    has_current_station_actions: bool = False
    unavailable: bool = False


@dataclass
class CityProbe:
    screen_point: tuple[int, int]
    panel: CityPanel
    row: int
    column: int
    already_current: bool = False


@dataclass
class TargetLabelProbe:
    label_center: tuple[int, int]
    click_points: list[tuple[int, int]]
    raw_text: str
    match_score: float


@dataclass
class CityRoutePlan:
    city_name: str
    source_row: str
    vertical_steps: int
    horizontal_steps: int
    sample_point: tuple[int, int]
    visibility: str
    confidence: str
    score: int


class MapNavigationError(RuntimeError):
    pass


def load_city_names() -> list[str]:
    names: set[str] = set()
    for path in [
        CITY_SAMPLE_PATH,
        RESOURCES_PATH / "goods" / "CityPosData.json",
        RESOURCES_PATH / "goods" / "CityGoodsSellData.json",
        RESOURCES_PATH / "stations" / "name2id.json",
    ]:
        if not Path(path).exists():
            continue
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if path == CITY_SAMPLE_PATH:
            names.update(data.get("cities", {}).keys())
        else:
            names.update(data.keys())

    tired_path = RESOURCES_PATH / "goods" / "CityTiredData.json"
    if tired_path.exists():
        data = json.loads(tired_path.read_text(encoding="utf-8"))
        for route in data.keys():
            names.update(route.split("-", 1))
    return sorted(names)


KNOWN_CITY_NAMES = load_city_names()
_CITY_SAMPLE_POINTS: dict[str, list[tuple[int, int]]] | None = None
_CITY_ROUTE_PLANS: dict[str, list[CityRoutePlan]] | None = None


ROUTE_ROW_STEPS = {
    "20260528_190604_origin_east": (0, "east"),
    "20260528_193126_south1_east": (1, "east"),
    # Captured in the Anita band after the missing factory was identified.
    # Keep it as a routed view, but still require panel verification.
    "20260528_205514_anita_factory": (1, "east"),
}

CONFIDENCE_SCORE = {"high": 0, "medium": 10, "low": 30}
VISIBILITY_SCORE = {
    "panel_verified": 0,
    "current_station_panel_verified": 0,
    "auto_probe": 4,
    "visible": 8,
    "manual": 10,
    "locked_or_unopened": 12,
    "edge": 18,
    "bottom_edge": 18,
    "occluded_by_task_panel": 35,
}


def load_city_sample_points() -> dict[str, list[tuple[int, int]]]:
    if not CITY_SAMPLE_PATH.exists():
        return {}

    data = json.loads(CITY_SAMPLE_PATH.read_text(encoding="utf-8"))
    points_by_city: dict[str, list[tuple[int, int]]] = {}
    for city, city_data in data.get("cities", {}).items():
        points: list[tuple[int, int]] = []
        for sample in city_data.get("samples", []):
            raw_point = sample.get("click_point") or sample.get("manual_point")
            if not raw_point or len(raw_point) != 2:
                continue
            point = (int(raw_point[0]), int(raw_point[1]))
            if is_valid_map_point(point):
                points.append(point)
        points_by_city[city] = dedupe_points(points, min_distance=24)
    return points_by_city


def city_sample_points(city_name: str) -> list[tuple[int, int]]:
    global _CITY_SAMPLE_POINTS
    if _CITY_SAMPLE_POINTS is None:
        _CITY_SAMPLE_POINTS = load_city_sample_points()
    return _CITY_SAMPLE_POINTS.get(city_name, [])


def route_steps_for_sample(sample: dict) -> tuple[int, int] | None:
    row_name = sample.get("row")
    if row_name not in ROUTE_ROW_STEPS:
        return None

    vertical_steps, horizontal_direction = ROUTE_ROW_STEPS[row_name]
    horizontal_steps = int(sample.get("step") or 0)
    if horizontal_direction == "west":
        horizontal_steps = -horizontal_steps
    return vertical_steps, horizontal_steps


def route_sample_point(sample: dict) -> tuple[int, int] | None:
    raw_point = sample.get("click_point") or sample.get("manual_point")
    if not raw_point or len(raw_point) != 2:
        return None
    return int(raw_point[0]), int(raw_point[1])


def route_sample_score(sample: dict, point: tuple[int, int], vertical_steps: int, horizontal_steps: int) -> int:
    score = CONFIDENCE_SCORE.get(sample.get("confidence"), 20)
    score += VISIBILITY_SCORE.get(sample.get("visibility"), 20)
    score += (vertical_steps + abs(horizontal_steps)) * 3

    if not is_valid_map_point(point):
        score += 30
    elif is_edge_point(point):
        score += 8

    return score


def load_city_route_plans() -> dict[str, list[CityRoutePlan]]:
    if not CITY_SAMPLE_PATH.exists():
        return {}

    data = json.loads(CITY_SAMPLE_PATH.read_text(encoding="utf-8"))
    plans_by_city: dict[str, list[CityRoutePlan]] = {}
    for city_name, city_data in data.get("cities", {}).items():
        plans: list[CityRoutePlan] = []
        for sample in city_data.get("samples", []):
            steps = route_steps_for_sample(sample)
            point = route_sample_point(sample)
            if not steps or not point:
                continue

            vertical_steps, horizontal_steps = steps
            plans.append(
                CityRoutePlan(
                    city_name=city_name,
                    source_row=sample.get("row") or "",
                    vertical_steps=vertical_steps,
                    horizontal_steps=horizontal_steps,
                    sample_point=point,
                    visibility=sample.get("visibility") or "",
                    confidence=sample.get("confidence") or "",
                    score=route_sample_score(sample, point, vertical_steps, horizontal_steps),
                )
            )

        plans.sort(key=lambda plan: (plan.score, plan.vertical_steps, abs(plan.horizontal_steps)))
        if plans:
            plans_by_city[city_name] = plans

    return plans_by_city


def city_route_plans(city_name: str) -> list[CityRoutePlan]:
    global _CITY_ROUTE_PLANS
    if _CITY_ROUTE_PLANS is None:
        _CITY_ROUTE_PLANS = load_city_route_plans()
    return _CITY_ROUTE_PLANS.get(city_name, [])


def best_city_route(city_name: str) -> CityRoutePlan | None:
    plans = city_route_plans(city_name)
    if not plans:
        return None
    return plans[0]


def prioritize_candidates(target_name: str, candidates: list[tuple[int, int]]) -> list[tuple[int, int]]:
    sample_points = city_sample_points(target_name)
    if not sample_points:
        return candidates

    def sort_key(point: tuple[int, int]) -> tuple[int, int, int]:
        nearest = min((point[0] - sample[0]) ** 2 + (point[1] - sample[1]) ** 2 for sample in sample_points)
        return nearest, point[1], point[0]

    return sorted(candidates, key=sort_key)


def normalize_city_name(text: str) -> tuple[str, float]:
    if text in KNOWN_CITY_NAMES:
        return text, 1.0
    matches = difflib.get_close_matches(text, KNOWN_CITY_NAMES, n=1, cutoff=0.58)
    if not matches:
        return text, 0.0
    name = matches[0]
    return name, difflib.SequenceMatcher(None, text, name).ratio()


def is_chinese_text(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def input_tap_exact(pos: tuple[int, int]):
    control_state.control.input_tap(
        int(control_state.control.ratio * pos[0]),
        int(control_state.control.ratio * pos[1]),
    )


def close_city_panel():
    if not read_city_panel(screenshot_image()):
        return False
    input_tap_exact((610, 300))
    time.sleep(0.8)
    return True


def zoom_out(times: int = 3):
    for _ in range(times):
        input_tap_exact((1152, 584))
        time.sleep(0.12)
    time.sleep(0.6)


def drag_view(direction: str, distance: int = 520, duration: int = 900):
    if direction == "east":
        input_swipe((900, 360), (900 - distance, 360), duration)
    elif direction == "west":
        input_swipe((360, 360), (360 + distance, 360), duration)
    elif direction == "south":
        input_swipe((640, 520), (640, 520 - distance), duration)
    elif direction == "north":
        input_swipe((640, 220), (640, 220 + distance), duration)
    else:
        raise ValueError(f"Unsupported map drag direction: {direction}")
    time.sleep(0.55 if duration <= 650 else 0.68)


def is_right_zoom_control(point: tuple[int, int]) -> bool:
    x, y = point
    return ZOOM_X_MIN <= x <= ZOOM_X_MAX and ZOOM_Y_MIN <= y <= MAP_BOTTOM


def is_main_quest_prompt(point: tuple[int, int]) -> bool:
    x, y = point
    return MAIN_QUEST_X_MIN <= x <= MAIN_QUEST_X_MAX and MAIN_QUEST_Y_MIN <= y <= MAIN_QUEST_Y_MAX


def is_forbidden_ui_point(point: tuple[int, int]) -> bool:
    return is_right_zoom_control(point) or is_main_quest_prompt(point)


def is_valid_map_point(point: tuple[int, int]) -> bool:
    x, y = point
    return 0 <= x < SCREEN_WIDTH and MAP_TOP <= y <= MAP_BOTTOM and not is_forbidden_ui_point(point)


def is_edge_point(point: tuple[int, int]) -> bool:
    x, y = point
    return (
        x < EDGE_X_MARGIN
        or x > SCREEN_WIDTH - EDGE_X_MARGIN
        or y < MAP_TOP + EDGE_Y_MARGIN
        or y > MAP_BOTTOM - EDGE_Y_MARGIN
    )


def is_safe_inner_point(point: tuple[int, int]) -> bool:
    return is_valid_map_point(point)


def dedupe_points(points: Iterable[tuple[int, int]], min_distance: int = 16) -> list[tuple[int, int]]:
    unique: list[tuple[int, int]] = []
    for point in points:
        if not is_valid_map_point(point):
            continue
        if all(abs(point[0] - old[0]) > min_distance or abs(point[1] - old[1]) > min_distance for old in unique):
            unique.append(point)
    return unique


def clamp_map_point(point: tuple[int, int]) -> tuple[int, int]:
    x, y = point
    x = max(8, min(SCREEN_WIDTH - 8, x))
    y = max(MAP_TOP + 6, min(MAP_BOTTOM - 6, y))
    return x, y


def probe_offsets(point: tuple[int, int]) -> list[tuple[int, int]]:
    if not is_edge_point(point):
        return [
            (0, 0),
            (0, -28),
            (-24, -18),
            (24, -18),
            (-28, 0),
            (28, 0),
            (0, 24),
        ]

    offsets = [(0, 0)]
    if point[0] < EDGE_X_MARGIN:
        offsets.extend([(14, 0), (22, 0)])
    elif point[0] > SCREEN_WIDTH - EDGE_X_MARGIN:
        offsets.extend([(-14, 0), (-22, 0)])

    if point[1] < MAP_TOP + EDGE_Y_MARGIN:
        offsets.extend([(0, 14), (0, 22)])
    elif point[1] > MAP_BOTTOM - EDGE_Y_MARGIN:
        offsets.extend([(0, -14), (0, -22)])

    return offsets


def drag_edge_point_towards_inner(point: tuple[int, int], distance: int = 220) -> bool:
    x, y = point
    moved = False
    if x < SAFE_X_MIN:
        logger.info(f"目标靠左，向西微调视口: point={point}")
        drag_view("west", distance=distance, duration=650)
        moved = True
    elif x > SAFE_X_MAX:
        logger.info(f"目标靠右，向东微调视口: point={point}")
        drag_view("east", distance=distance, duration=650)
        moved = True

    if y < SAFE_Y_MIN:
        logger.info(f"目标靠上，向北微调视口: point={point}")
        drag_view("north", distance=distance, duration=650)
        moved = True
    elif y > SAFE_Y_MAX:
        logger.info(f"目标靠下，向南微调视口: point={point}")
        drag_view("south", distance=distance, duration=650)
        moved = True

    return moved


def reset_to_northwest(
    zoom_times: int = 3,
    west_times: int = 10,
    north_times: int = 8,
    duration: int = 900,
):
    close_city_panel()
    zoom_out(zoom_times)
    for _ in range(west_times):
        input_swipe((360, 360), (980, 360), duration)
        time.sleep(0.18)
    for _ in range(north_times):
        input_swipe((640, 240), (640, 560), duration)
        time.sleep(0.18)


def nudge_route_point_into_clickable_area(point: tuple[int, int], distance: int = 260) -> bool:
    moved = False
    if is_right_zoom_control(point) or point[0] > SCREEN_WIDTH - EDGE_X_MARGIN:
        logger.info(f"Route sample is near right-side UI, nudging east. point={point}")
        drag_view("east", distance=distance, duration=650)
        moved = True

    if is_main_quest_prompt(point) or point[1] > MAP_BOTTOM - EDGE_Y_MARGIN:
        logger.info(f"Route sample is near lower UI, nudging south. point={point}")
        drag_view("south", distance=distance, duration=650)
        moved = True
    elif point[1] < MAP_TOP + EDGE_Y_MARGIN:
        logger.info(f"Route sample is near top edge, nudging north. point={point}")
        drag_view("north", distance=distance, duration=650)
        moved = True

    return moved


def navigate_to_route_view(plan: CityRoutePlan, drag_distance: int = 520):
    logger.info(
        "Route-first map navigation: "
        f"{plan.city_name} row={plan.vertical_steps} column={plan.horizontal_steps} "
        f"sample={plan.sample_point} score={plan.score}"
    )
    reset_to_northwest()

    for _ in range(plan.vertical_steps):
        drag_view("south", distance=drag_distance)

    horizontal_direction = "east" if plan.horizontal_steps >= 0 else "west"
    for _ in range(abs(plan.horizontal_steps)):
        drag_view(horizontal_direction, distance=drag_distance)

    nudge_route_point_into_clickable_area(plan.sample_point)


def find_icon_candidates(image) -> list[tuple[int, int]]:
    hsv = cv.cvtColor(image, cv.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 120)).astype("uint8") * 255

    # Persistent UI: top bar, bottom task panel, and lower-right zoom controls.
    mask[:MAP_TOP, :] = 0
    mask[MAP_BOTTOM:, :] = 0
    mask[ZOOM_Y_MIN:MAP_BOTTOM, ZOOM_X_MIN:ZOOM_X_MAX] = 0
    mask[MAIN_QUEST_Y_MIN:MAIN_QUEST_Y_MAX, MAIN_QUEST_X_MIN:MAIN_QUEST_X_MAX] = 0

    count, labels, stats, centers = cv.connectedComponentsWithStats(mask)
    candidates: list[tuple[int, int]] = []
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if not (30 <= area <= 700 and 6 <= width <= 42 and 6 <= height <= 42):
            continue
        cx, cy = centers[index]
        point = (int(round(cx)), int(round(cy)))
        if not is_valid_map_point(point):
            continue
        if all(abs(point[0] - old[0]) > 18 or abs(point[1] - old[1]) > 18 for old in candidates):
            candidates.append(point)

    return sorted(candidates, key=lambda point: (point[1], point[0]))


def find_white_marker_candidates(image) -> list[tuple[int, int]]:
    hsv = cv.cvtColor(image, cv.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] < 80) & (hsv[:, :, 2] > 155)).astype("uint8") * 255

    # This intentionally only finds candidates. White markers are not clicked
    # by the live scanner until their hitboxes are manually calibrated.
    mask[:MAP_TOP, :] = 0
    mask[MAP_BOTTOM:, :] = 0
    mask[ZOOM_Y_MIN:MAP_BOTTOM, ZOOM_X_MIN:ZOOM_X_MAX] = 0
    mask[MAIN_QUEST_Y_MIN:MAIN_QUEST_Y_MAX, MAIN_QUEST_X_MIN:MAIN_QUEST_X_MAX] = 0

    count, labels, stats, centers = cv.connectedComponentsWithStats(mask)
    candidates: list[tuple[int, int]] = []
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if not (20 <= area <= 1300 and 6 <= width <= 55 and 8 <= height <= 65):
            continue
        cx, cy = centers[index]
        point = (int(round(cx)), int(round(cy)))
        if not is_valid_map_point(point):
            continue
        if all(abs(point[0] - old[0]) > 18 or abs(point[1] - old[1]) > 18 for old in candidates):
            candidates.append(point)

    return sorted(candidates, key=lambda point: (point[1], point[0]))


def read_city_panel(image) -> CityPanel | None:
    data = predict(image, no_crop=True)
    has_travel_button = any(item["text"] == "前往目的地" for item in data)
    has_current_station_actions = any(
        item["text"] in {"拖车服务", "行驶辅助", "补充燃料", "招揽乘客", "交易所", "每周新闻"}
        for item in data
    )
    unavailable = any("未开放" in item["text"] for item in data)
    if not has_travel_button and not has_current_station_actions and not unavailable:
        return None

    title_candidates = [
        item
        for item in data
        if is_chinese_text(item["text"])
        and ":" not in item["text"]
        and "：" not in item["text"]
        and len(item["text"]) <= 12
        and 650 <= item["position"][0][0] <= 980
        and 80 <= item["position"][0][1] <= 155
    ]
    if not title_candidates:
        return None

    title = max(title_candidates, key=lambda item: item["score"])
    raw_name = title["text"]
    name, match_score = normalize_city_name(raw_name)
    return CityPanel(
        name=name,
        raw_name=raw_name,
        name_match_score=match_score,
        score=title["score"],
        position=title["position"],
        has_travel_button=has_travel_button,
        has_current_station_actions=has_current_station_actions,
        unavailable=unavailable,
    )


def box_center(position: list[list[float]]) -> tuple[int, int]:
    xs = [point[0] for point in position]
    ys = [point[1] for point in position]
    return int(round(sum(xs) / len(xs))), int(round(sum(ys) / len(ys)))


def is_map_text_box(position: list[list[float]]) -> bool:
    xs = [point[0] for point in position]
    ys = [point[1] for point in position]
    center = box_center(position)
    return (
        0 <= min(xs) <= SCREEN_WIDTH
        and 0 <= max(xs) <= SCREEN_WIDTH
        and MAP_TOP <= min(ys)
        and max(ys) <= MAP_BOTTOM
        and not is_right_zoom_control(center)
    )


def find_target_label_probes(image, target_name: str) -> list[TargetLabelProbe]:
    probes: list[TargetLabelProbe] = []
    for item in predict(image, no_crop=True):
        if not is_map_text_box(item["position"]):
            continue

        text = item["text"].strip().replace(" ", "")
        if not text or not is_chinese_text(text) or len(text) > 12:
            continue

        name, match_score = normalize_city_name(text)
        if name != target_name or match_score < 0.62:
            continue

        cx, cy = box_center(item["position"])
        points: list[tuple[int, int]] = []
        for dx in (0, -12, 12):
            for dy in (-50, -38, -26, -14, -4):
                points.append(clamp_map_point((cx + dx, cy + dy)))

        probes.append(
            TargetLabelProbe(
                label_center=(cx, cy),
                click_points=dedupe_points(points, min_distance=10),
                raw_text=text,
                match_score=match_score,
            )
        )

    return probes


def find_label_probe_points(image, target_name: str) -> list[tuple[int, int]]:
    points: list[tuple[int, int]] = []
    for probe in find_target_label_probes(image, target_name):
        points.extend(probe.click_points)
    return dedupe_points(points, min_distance=10)


def probe_city_point(
    point: tuple[int, int],
    target_name: str,
    row: int,
    column: int,
) -> CityProbe | None:
    for dx, dy in probe_offsets(point):
        probe_point = clamp_map_point((point[0] + dx, point[1] + dy))
        if not is_valid_map_point(probe_point) or not is_safe_inner_point(probe_point):
            continue

        close_city_panel()
        input_tap_exact(probe_point)
        time.sleep(0.75)
        panel = read_city_panel(screenshot_image())
        if not panel:
            continue

        logger.info(f"候选 {probe_point} => {panel.name} (raw={panel.raw_name})")
        if panel.name == target_name:
            return CityProbe(screen_point=probe_point, panel=panel, row=row, column=column)

        close_city_panel()
        continue

    close_city_panel()
    return None


def current_station_probe(target_name: str) -> CityProbe:
    return CityProbe(
        screen_point=(-1, -1),
        panel=CityPanel(
            name=target_name,
            raw_name=target_name,
            name_match_score=1.0,
            score=1.0,
            position=[],
            has_current_station_actions=True,
        ),
        row=-1,
        column=-1,
        already_current=True,
    )


def rounded_point(point: tuple[float, float]) -> tuple[int, int]:
    return int(round(point[0])), int(round(point[1]))


def is_navigation_target_safe(point: tuple[int, int]) -> bool:
    x, y = point
    return (
        NAV_TARGET_X_MIN <= x <= NAV_TARGET_X_MAX
        and NAV_TARGET_Y_MIN <= y <= NAV_TARGET_Y_MAX
        and is_valid_map_point(point)
    )


def is_navigation_target_near_safe(point: tuple[int, int], margin: int = 320) -> bool:
    x, y = point
    return (
        NAV_TARGET_X_MIN - margin <= x <= NAV_TARGET_X_MAX + margin
        and NAV_TARGET_Y_MIN - margin <= y <= NAV_TARGET_Y_MAX + margin
    )


def clamp_drag_distance(distance: float, drag_distance: int) -> int:
    max_distance = min(drag_distance, MAX_COORDINATE_DRAG_DISTANCE)
    return int(max(MIN_COORDINATE_DRAG_DISTANCE, min(max_distance, round(distance))))


def projected_target_drag_plan(point: tuple[int, int], drag_distance: int = 520) -> tuple[str, int] | None:
    x, y = point
    x_delta = 0
    y_delta = 0
    if x > NAV_TARGET_X_MAX or x < NAV_TARGET_X_MIN:
        x_delta = x - NAV_TARGET_CENTER_X
    if y > NAV_TARGET_Y_MAX or y < NAV_TARGET_Y_MIN:
        y_delta = y - NAV_TARGET_CENTER_Y

    if not x_delta and not y_delta:
        return None

    x_weight = abs(x_delta) / (NAV_TARGET_X_MAX - NAV_TARGET_X_MIN)
    y_weight = abs(y_delta) / (NAV_TARGET_Y_MAX - NAV_TARGET_Y_MIN)
    if x_weight >= y_weight:
        direction = "east" if x_delta > 0 else "west"
        distance = clamp_drag_distance(abs(x_delta) * 0.38, drag_distance)
    else:
        direction = "south" if y_delta > 0 else "north"
        distance = clamp_drag_distance(abs(y_delta) * 0.65, drag_distance)
    return direction, distance


def drag_projected_target_towards_safe_area(point: tuple[int, int], drag_distance: int = 520) -> bool:
    plan = projected_target_drag_plan(point, drag_distance=drag_distance)
    if not plan:
        return False

    direction, distance = plan
    logger.info(f"目标不在安全点击区，单轴移动地图: point={point} direction={direction} distance={distance}")
    drag_view(direction, distance=distance)
    return True


def scan_coordinate_city(
    target_name: str,
    *,
    drag_distance: int = 520,
    reset_first: bool = True,
    max_steps: int = 6,
) -> CityProbe | None:
    station = station_by_name(target_name)
    if not station:
        logger.warning(f"目标站点没有全局地图坐标: {target_name}")
        return None

    close_city_panel()
    if reset_first:
        zoom_out()

    last_target_point: tuple[int, int] | None = None
    stalled_steps = 0
    for step in range(max_steps):
        image = screenshot_image()
        location = locate_map_view(image)
        if not location:
            logger.warning("未能通过站点星座定位当前地图视口")
            if last_target_point and is_navigation_target_near_safe(last_target_point):
                visible_probe = scan_visible_city(
                    target_name,
                    row=-2,
                    column=step,
                    limit=8,
                    allow_edge_recenter=True,
                    use_sample_points=False,
                    use_icon_candidates=False,
                )
                if visible_probe:
                    logger.info(f"定位丢失后当前视口已确认目标站点: {target_name} @ {visible_probe.screen_point}")
                    return visible_probe
            return None

        names = ", ".join(match.name for match in location.matches)
        logger.info(
            f"地图视口定位: matches={location.match_count} "
            f"mean_error={location.mean_error} scale={location.scale} [{names}]"
        )

        target_point = rounded_point(project_station(station, location))
        logger.info(f"目标投影点: {target_name} -> {target_point}")
        if last_target_point:
            movement = ((target_point[0] - last_target_point[0]) ** 2 + (target_point[1] - last_target_point[1]) ** 2) ** 0.5
            if movement < 24 and not is_navigation_target_safe(target_point):
                stalled_steps += 1
                logger.warning(f"地图移动后目标投影变化过小，可能已撞到地图边界: movement={movement:.1f}")
            else:
                stalled_steps = 0
            if stalled_steps >= 2:
                return None
        last_target_point = target_point

        if is_navigation_target_safe(target_point):
            probe = probe_city_point(target_point, target_name, row=-2, column=step)
            if probe:
                logger.info(f"坐标定位已确认目标站点: {target_name} @ {probe.screen_point}")
                return probe
            visible_probe = scan_visible_city(
                target_name,
                row=-2,
                column=step,
                limit=8,
                allow_edge_recenter=False,
                use_sample_points=False,
                use_icon_candidates=False,
            )
            if visible_probe:
                logger.info(f"坐标点附近可见扫描已确认目标站点: {target_name} @ {visible_probe.screen_point}")
                return visible_probe
            logger.warning(f"坐标定位点击未确认 {target_name}，交给兜底扫描")
            return None

        if not drag_projected_target_towards_safe_area(target_point, drag_distance=drag_distance):
            logger.warning(f"目标投影点不可点击且无法判断拖动方向: {target_point}")
            return None

    logger.warning(f"坐标定位 {max_steps} 次移动后仍未让目标进入安全点击区: {target_name}")
    if last_target_point and is_navigation_target_near_safe(last_target_point):
        visible_probe = scan_visible_city(
            target_name,
            row=-2,
            column=max_steps,
            limit=8,
            allow_edge_recenter=True,
            use_sample_points=False,
            use_icon_candidates=False,
        )
        if visible_probe:
            logger.info(f"坐标步数耗尽后当前视口已确认目标站点: {target_name} @ {visible_probe.screen_point}")
            return visible_probe
    return None


def scan_visible_city(
    target_name: str,
    row: int = 0,
    column: int = 0,
    limit: int = 35,
    allow_edge_recenter: bool = True,
    use_sample_points: bool = True,
    use_icon_candidates: bool = True,
) -> CityProbe | None:
    close_city_panel()
    image = screenshot_image()
    candidates = (
        prioritize_candidates(target_name, find_icon_candidates(image))[:limit]
        if use_icon_candidates
        else []
    )
    inner_candidates = [point for point in candidates if is_safe_inner_point(point)]
    deferred_candidates = [point for point in candidates if not is_safe_inner_point(point)]
    logger.info(
        f"当前视口候选点数量: {len(candidates)} "
        f"(安全内区 {len(inner_candidates)}, 延后 {len(deferred_candidates)})"
    )

    label_probes = find_target_label_probes(image, target_name)
    for label_probe in label_probes:
        logger.info(
            f"目标文字候选: {label_probe.raw_text} "
            f"center={label_probe.label_center} points={label_probe.click_points}"
        )
        needs_recenter = not is_safe_inner_point(label_probe.label_center) or any(
            is_edge_point(point) for point in label_probe.click_points
        )
        if allow_edge_recenter and needs_recenter and drag_edge_point_towards_inner(label_probe.label_center):
            return scan_visible_city(
                target_name,
                row=row,
                column=column,
                limit=limit,
                allow_edge_recenter=False,
                use_sample_points=use_sample_points,
                use_icon_candidates=use_icon_candidates,
            )

        for point in label_probe.click_points:
            probe = probe_city_point(point, target_name, row, column)
            if probe:
                return probe

    if use_sample_points:
        sample_points = city_sample_points(target_name)
        if sample_points:
            logger.info(f"目标历史样本候选点: {sample_points}")
        for point in sample_points:
            probe = probe_city_point(point, target_name, row, column)
            if probe:
                return probe

    for point in inner_candidates:
        probe = probe_city_point(point, target_name, row, column)
        if probe:
            return probe

    return None


def scan_map_for_city(
    target_name: str,
    rows: int = 3,
    columns: int = 5,
    drag_distance: int = 520,
    reset_first: bool = True,
    limit: int = 35,
    coordinate_first: bool = True,
    route_first: bool = True,
    fallback_scan: bool = True,
) -> CityProbe | None:
    if target_name not in KNOWN_CITY_NAMES:
        raise MapNavigationError(f"未找到已知站点: {target_name}")

    if coordinate_first:
        probe = scan_coordinate_city(
            target_name,
            drag_distance=drag_distance,
            reset_first=reset_first,
        )
        if probe:
            return probe
        if not fallback_scan:
            return None
        logger.warning(f"坐标定位未确认 {target_name}，退回旧地图扫描流程。")

    route_plan = best_city_route(target_name) if route_first and reset_first else None
    if route_plan:
        navigate_to_route_view(route_plan, drag_distance=drag_distance)
        probe = scan_visible_city(
            target_name,
            row=route_plan.vertical_steps,
            column=route_plan.horizontal_steps,
            limit=limit,
        )
        if probe:
            logger.info(f"路线优先已确认目标站点: {target_name} @ {probe.screen_point}")
            return probe

        logger.warning(f"路线优先未确认 {target_name}，退回全图扫描。")
        reset_to_northwest()
    elif reset_first:
        logger.info("复位到西北地图边界")
        reset_to_northwest()
    else:
        close_city_panel()

    direction = "east"
    for row in range(rows):
        column_range: Iterable[int] = range(columns)
        for column in column_range:
            logger.info(f"扫描地图视口 row={row} column={column}")
            probe = scan_visible_city(target_name, row=row, column=column, limit=limit)
            if probe:
                logger.info(f"已确认目标站点: {target_name} @ {probe.screen_point}")
                return probe

            if column < columns - 1:
                drag_view(direction, distance=drag_distance)

        if row < rows - 1:
            drag_view("south", distance=drag_distance)
            direction = "west" if direction == "east" else "east"

    logger.error(f"扫描地图未找到目标站点: {target_name}")
    return None


def click_travel_buttons() -> bool:
    logger.info("点击前往目的地")
    if not click_image(
        RESOURCES_PATH / "map/go_station.png",
        cropped_pos1=(937, 605),
        cropped_pos2=(1218, 679),
        trynum=5,
        check_err=False,
    ):
        return False

    time.sleep(1.0)
    click_image(
        RESOURCES_PATH / "map/join_station.png",
        cropped_pos1=(719, 405),
        cropped_pos2=(927, 485),
        trynum=5,
        check_err=False,
    )
    return True


def select_station_on_map(
    target_name: str,
    *,
    travel: bool = False,
    reset_first: bool = True,
    rows: int = 3,
    columns: int = 5,
    drag_distance: int = 520,
    limit: int = 35,
    current_station: str | None = None,
    coordinate_first: bool = True,
    route_first: bool = True,
    fallback_scan: bool = True,
) -> CityProbe | None:
    if current_station:
        normalized_current, score = normalize_city_name(current_station)
        if normalized_current == target_name and score >= 0.58:
            logger.info(f"已在目标站点: {target_name}")
            close_city_panel()
            return current_station_probe(target_name)

    probe = scan_map_for_city(
        target_name,
        rows=rows,
        columns=columns,
        drag_distance=drag_distance,
        reset_first=reset_first,
        limit=limit,
        coordinate_first=coordinate_first,
        route_first=route_first,
        fallback_scan=fallback_scan,
    )
    if not probe:
        return None

    if travel and not click_travel_buttons():
        raise MapNavigationError(f"已选中 {target_name}，但未找到前往目的地按钮")

    if not travel:
        close_city_panel()
    return probe


def open_station_map_from_home():
    input_tap(CITY_DEPART_BUTTON)
    time.sleep(0.8)
    wait_stopped(threshold=7100000)


def refresh_station_map_from_map(*, zoom: bool = True):
    logger.info("返回城市页面并重新打开站点地图")
    input_tap_exact(MAP_BACK_BUTTON)
    time.sleep(0.8)
    wait_stopped(threshold=7100000)

    input_tap(CITY_DEPART_BUTTON)
    time.sleep(0.8)
    wait_stopped(threshold=7100000)

    if zoom:
        zoom_out()
