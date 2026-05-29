"""
Reset the current map view to a repeatable northwest origin at minimum zoom.

Run this while the game is on the route/map page.
"""

import argparse
import sys
import time
from pathlib import Path

from loguru import logger

project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(project_root))

from core.control.control import connect, input_swipe, input_tap


def close_panel():
    input_tap((610, 300))
    time.sleep(0.5)


def zoom_out(times: int):
    for _ in range(times):
        input_tap((1152, 584))
        time.sleep(0.12)


def drag_to_northwest(west_times: int, north_times: int, duration: int):
    for _ in range(west_times):
        input_swipe((360, 360), (980, 360), duration)
        time.sleep(0.2)
    for _ in range(north_times):
        input_swipe((640, 240), (640, 560), duration)
        time.sleep(0.2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zoom-times", type=int, default=8)
    parser.add_argument("--west-times", type=int, default=10)
    parser.add_argument("--north-times", type=int, default=8)
    parser.add_argument("--duration", type=int, default=900)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if not args.verbose:
        logger.remove()

    if not connect():
        print("Failed to connect emulator. Check ADB/MuMu settings first.")
        return 1

    close_panel()
    zoom_out(args.zoom_times)
    drag_to_northwest(args.west_times, args.north_times, args.duration)
    print("Map reset to northwest origin candidate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
