"""
No-click station-map viewport locator.

The current map background is animated, so this module ignores background
features and fits visible station icon candidates to HomeStationFactory minimap
coordinates. The coordinate source uses 修格里城 as (0, 0).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

import cv2 as cv
import numpy as np

from core.utils.utils import RESOURCES_PATH


WORLD_PATH = RESOURCES_PATH / "map" / "CityWorld2026.json"
MAP_TOP = 90
MAP_BOTTOM = 705
SCREEN_WIDTH = 1280
ZOOM_X_MIN = 1120
ZOOM_X_MAX = 1185
ZOOM_Y_MIN = 320
MAIN_QUEST_X_MIN = 850
MAIN_QUEST_X_MAX = 1225
MAIN_QUEST_Y_MIN = 625
MAIN_QUEST_Y_MAX = 705

CALIBRATED_MAP_SCALE = 0.3325
MIN_MATCH_COUNT = 4
MAX_MEAN_ERROR = 12.0
CITY_ICON_AREA_MIN = 45
CITY_ICON_AREA_MAX = 220
CITY_ICON_SIZE_MIN = 7
CITY_ICON_SIZE_MAX = 24


@dataclass(frozen=True)
class WorldStation:
    id: int
    name: str
    x: float
    y: float
    map_icon_path: str
    attached_to_city: int
    is_open: bool
    is_ban_stop: bool


@dataclass(frozen=True)
class MapMatch:
    name: str
    world: tuple[float, float]
    projected: tuple[float, float]
    candidate: tuple[int, int]
    distance: float


@dataclass(frozen=True)
class MapLocateResult:
    scale: float
    tx: float
    ty: float
    score: float
    mean_error: float
    matches: tuple[MapMatch, ...]
    candidates: tuple[tuple[int, int], ...]

    @property
    def match_count(self) -> int:
        return len(self.matches)


def load_world_stations() -> list[WorldStation]:
    data = json.loads(WORLD_PATH.read_text(encoding="utf-8"))
    return [
        WorldStation(
            id=int(item["id"]),
            name=item["name"],
            x=float(item["x"]),
            y=float(item["y"]),
            map_icon_path=item.get("map_icon_path", ""),
            attached_to_city=int(item.get("attached_to_city", -1)),
            is_open=bool(item.get("is_open")),
            is_ban_stop=bool(item.get("is_ban_stop")),
        )
        for item in data.get("stations", [])
    ]


def station_by_name(name: str) -> WorldStation | None:
    for station in load_world_stations():
        if station.name == name:
            return station
    return None


def project_world_point(x: float, y: float, scale: float, tx: float, ty: float) -> tuple[float, float]:
    return scale * x + tx, -scale * y + ty


def project_station(station: WorldStation, result: MapLocateResult) -> tuple[float, float]:
    return project_world_point(station.x, station.y, result.scale, result.tx, result.ty)


def is_right_zoom_control(point: tuple[int, int]) -> bool:
    x, y = point
    return ZOOM_X_MIN <= x <= ZOOM_X_MAX and ZOOM_Y_MIN <= y <= MAP_BOTTOM


def is_main_quest_prompt(point: tuple[int, int]) -> bool:
    x, y = point
    return MAIN_QUEST_X_MIN <= x <= MAIN_QUEST_X_MAX and MAIN_QUEST_Y_MIN <= y <= MAIN_QUEST_Y_MAX


def is_valid_map_point(point: tuple[int, int]) -> bool:
    x, y = point
    return 0 <= x < SCREEN_WIDTH and MAP_TOP <= y <= MAP_BOTTOM and not is_right_zoom_control(point) and not is_main_quest_prompt(point)


def stable_region_mask(shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[MAP_TOP:MAP_BOTTOM, :] = 255
    mask[ZOOM_Y_MIN:MAP_BOTTOM, ZOOM_X_MIN:ZOOM_X_MAX] = 0
    mask[MAIN_QUEST_Y_MIN:MAIN_QUEST_Y_MAX, MAIN_QUEST_X_MIN:MAIN_QUEST_X_MAX] = 0
    return mask


def is_station_icon_component(
    hsv: np.ndarray,
    labels: np.ndarray,
    index: int,
    width: int,
    height: int,
    area: int,
) -> bool:
    if not (
        CITY_ICON_AREA_MIN <= area <= CITY_ICON_AREA_MAX
        and CITY_ICON_SIZE_MIN <= width <= CITY_ICON_SIZE_MAX
        and CITY_ICON_SIZE_MIN <= height <= CITY_ICON_SIZE_MAX
    ):
        return False

    region = labels == index
    median_h = int(np.median(hsv[:, :, 0][region]))
    median_s = int(np.median(hsv[:, :, 1][region]))
    median_v = int(np.median(hsv[:, :, 2][region]))

    is_gold_station = 15 <= median_h <= 35 and median_s >= 185 and median_v >= 150
    is_cyan_station = 82 <= median_h <= 125 and median_s >= 150 and median_v >= 125
    is_red_station = (
        (median_h <= 8 or median_h >= 172)
        and median_s >= 170
        and median_v >= 135
        and area <= 140
        and width <= 18
        and height <= 18
    )
    return is_gold_station or is_cyan_station or is_red_station


def detect_station_icon_candidates(image) -> list[tuple[int, int]]:
    hsv = cv.cvtColor(image, cv.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 120)).astype("uint8") * 255
    mask = cv.bitwise_and(mask, stable_region_mask(mask.shape))

    count, labels, stats, centers = cv.connectedComponentsWithStats(mask)
    candidates: list[tuple[int, int]] = []
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if not is_station_icon_component(hsv, labels, index, width, height, area):
            continue
        point = (int(round(centers[index][0])), int(round(centers[index][1])))
        if not is_valid_map_point(point):
            continue
        if all(abs(point[0] - old[0]) > 18 or abs(point[1] - old[1]) > 18 for old in candidates):
            candidates.append(point)

    return sorted(candidates, key=lambda point: (point[1], point[0]))


def nearest_candidate(
    point: tuple[float, float],
    candidates: list[tuple[int, int]],
) -> tuple[tuple[int, int], float] | None:
    if not candidates:
        return None
    px, py = point
    best = min(candidates, key=lambda item: (item[0] - px) ** 2 + (item[1] - py) ** 2)
    return best, math.hypot(best[0] - px, best[1] - py)


def score_transform(
    stations: list[WorldStation],
    candidates: list[tuple[int, int]],
    scale: float,
    tx: float,
    ty: float,
    threshold: float,
) -> tuple[float, list[MapMatch]]:
    used_candidates: set[tuple[int, int]] = set()
    matches: list[MapMatch] = []
    for station in stations:
        sx, sy = project_world_point(station.x, station.y, scale, tx, ty)
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
            MapMatch(
                name=station.name,
                world=(station.x, station.y),
                projected=(round(sx, 2), round(sy, 2)),
                candidate=candidate,
                distance=round(distance, 2),
            )
        )

    if not matches:
        return -1e9, matches

    mean_error = sum(match.distance for match in matches) / len(matches)
    score = len(matches) * 100 - mean_error * 3
    if len(matches) >= 3:
        score += 80
    if len(matches) >= 5:
        score += 160
    score -= abs(scale - CALIBRATED_MAP_SCALE) * 1000
    return score, matches


def locate_candidates(
    candidates: list[tuple[int, int]],
    *,
    stations: list[WorldStation] | None = None,
    scale_min: float = 0.325,
    scale_max: float = 0.34,
    scale_step: float = 0.0025,
    threshold: float = 28.0,
) -> MapLocateResult | None:
    stations = stations or load_world_stations()
    best: MapLocateResult | None = None
    scales = np.arange(scale_min, scale_max + scale_step / 2, scale_step)
    for candidate in candidates:
        cx, cy = candidate
        for station in stations:
            for scale in scales:
                scale = float(scale)
                tx = cx - scale * station.x
                ty = cy + scale * station.y
                score, matches = score_transform(stations, candidates, scale, tx, ty, threshold)
                if not matches:
                    continue
                mean_error = sum(match.distance for match in matches) / len(matches)
                result = MapLocateResult(
                    scale=round(scale, 5),
                    tx=round(float(tx), 3),
                    ty=round(float(ty), 3),
                    score=round(score, 3),
                    mean_error=round(mean_error, 3),
                    matches=tuple(matches),
                    candidates=tuple(candidates),
                )
                if best is None or result.score > best.score:
                    best = result

    if not best:
        return None
    candidate_xs = [match.candidate[0] for match in best.matches]
    candidate_ys = [match.candidate[1] for match in best.matches]
    has_stable_spread = (
        max(candidate_xs) - min(candidate_xs) >= 180
        and max(candidate_ys) - min(candidate_ys) >= 80
    )
    reliable = (
        (best.match_count >= 5 and best.mean_error <= 6.0)
        or (best.match_count >= 4 and best.mean_error <= 3.0)
        or (best.match_count >= 3 and best.mean_error <= 1.2 and has_stable_spread)
    )
    if not reliable:
        return None
    return best


def locate_map_view(image) -> MapLocateResult | None:
    return locate_candidates(detect_station_icon_candidates(image))
