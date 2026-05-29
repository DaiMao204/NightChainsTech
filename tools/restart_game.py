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
from core.preset.page_state import capture_page_state, restart_game_to_main


def main() -> int:
    parser = argparse.ArgumentParser(description="Restart Resonance and wait for the main map.")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--label", default="manual_restart_game")
    args = parser.parse_args()

    if not connect():
        print(json.dumps({"ok": False, "error": "connect failed"}, ensure_ascii=False))
        return 1

    result = restart_game_to_main(label=args.label, timeout=args.timeout)
    capture_page_state(
        f"{args.label}_final",
        extra={
            "recovered": result.recovered,
            "action": result.action,
            "steps": result.steps,
        },
    )
    print(
        json.dumps(
            {
                "ok": result.recovered,
                "recovery": {
                    "before": asdict(result.before),
                    "after": asdict(result.after),
                    "recovered": result.recovered,
                    "action": result.action,
                    "steps": result.steps,
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result.recovered else 1


if __name__ == "__main__":
    raise SystemExit(main())
