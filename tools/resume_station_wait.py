from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.control.control import connect
from core.preset.page_state import capture_page_state, classify_page
from core.preset.station import STATION


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume waiting from an existing route/event/fight page.")
    parser.add_argument("--label", default="resume_station_wait")
    args = parser.parse_args()

    if not connect():
        print(json.dumps({"ok": False, "error": "connect failed"}, ensure_ascii=False))
        return 1

    start_state = classify_page()
    result = STATION(True).wait()
    end_state = capture_page_state(args.label, extra={"result": bool(result)})
    print(
        json.dumps(
            {
                "ok": bool(result),
                "start_state": asdict(start_state),
                "end_state": asdict(end_state),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
