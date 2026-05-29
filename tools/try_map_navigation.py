"""
Try the modern map scanner from the current map page.

By default this is a dry run: it confirms the city by opening the right-side
panel, then closes the panel without clicking travel.
"""

import argparse
import sys
from pathlib import Path

from loguru import logger

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from core.control.control import connect
from core.preset.map_navigation import (
    KNOWN_CITY_NAMES,
    open_station_map_from_home,
    refresh_station_map_from_map,
    select_station_on_map,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", choices=KNOWN_CITY_NAMES)
    parser.add_argument("--open-map", action="store_true", help="tap the home map entry first")
    parser.add_argument("--refresh-map", action="store_true", help="return to city and reopen the map before scanning")
    parser.add_argument("--retry-refresh", action="store_true", help="refresh the map once and retry if the first scan fails")
    parser.add_argument("--travel", action="store_true", help="click travel after the city is confirmed")
    parser.add_argument("--no-coordinate", action="store_true", help="disable coordinate-first map positioning")
    parser.add_argument("--coordinate-only", action="store_true", help="do not fall back to route or candidate scanning")
    parser.add_argument("--no-route", action="store_true", help="disable route-first target positioning")
    parser.add_argument("--no-reset", action="store_true", help="scan from current viewport")
    parser.add_argument("--rows", type=int, default=3)
    parser.add_argument("--columns", type=int, default=5)
    parser.add_argument("--drag-distance", type=int, default=520)
    parser.add_argument("--limit", type=int, default=35)
    parser.add_argument("--current-station", help="known current station name; skips map scan when target matches")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.verbose:
        logger.remove()

    if not connect():
        print("Failed to connect emulator. Check ADB/MuMu settings first.")
        return 1

    if args.open_map:
        open_station_map_from_home()

    if args.refresh_map:
        refresh_station_map_from_map()

    probe = select_station_on_map(
        args.target,
        travel=args.travel,
        reset_first=not args.no_reset,
        rows=args.rows,
        columns=args.columns,
        drag_distance=args.drag_distance,
        limit=args.limit,
        current_station=args.current_station,
        coordinate_first=not args.no_coordinate,
        route_first=not args.no_route and not args.coordinate_only,
        fallback_scan=not args.coordinate_only,
    )
    if not probe and args.retry_refresh:
        refresh_station_map_from_map()
        probe = select_station_on_map(
            args.target,
            travel=args.travel,
            reset_first=not args.no_reset,
            rows=args.rows,
            columns=args.columns,
            drag_distance=args.drag_distance,
            limit=args.limit,
            current_station=args.current_station,
            coordinate_first=not args.no_coordinate,
            route_first=not args.no_route and not args.coordinate_only,
            fallback_scan=not args.coordinate_only,
        )

    if not probe:
        print(f"未找到目标站点: {args.target}")
        return 2

    if probe.already_current:
        mode = "已在目标站点"
    else:
        mode = "已发起前往" if args.travel else "仅确认，未前往"
    print(
        f"{mode}: {probe.panel.name} "
        f"point={probe.screen_point} row={probe.row} column={probe.column}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
