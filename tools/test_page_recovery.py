from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auto.run_business.main import go_business
from core.control.control import connect
from core.preset.page_state import (
    PageKind,
    capture_page_state,
    classify_page,
    recover_page_state,
    recover_trade_page,
)


def state_dict(label: str):
    state = classify_page()
    return {"label": label, "state": asdict(state)}


def recovery_dict(label: str, target: PageKind, allow_go_home: bool = False):
    result = recover_page_state(target, label=label, allow_go_home=allow_go_home)
    return {
        "label": label,
        "recovery": {
            "before": asdict(result.before),
            "after": asdict(result.after),
            "recovered": result.recovered,
            "action": result.action,
            "steps": result.steps,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test page classification and recovery.")
    parser.add_argument(
        "--scenario",
        choices=("classify", "business-pages", "trade-switch"),
        default="business-pages",
    )
    args = parser.parse_args()

    if not connect():
        print(json.dumps({"ok": False, "error": "connect failed"}, ensure_ascii=False))
        return 1

    steps = [state_dict("start")]
    if args.scenario == "classify":
        capture_page_state("test_page_recovery_classify")
        print(json.dumps({"ok": True, "steps": steps}, ensure_ascii=False, indent=2))
        return 0

    if args.scenario == "trade-switch":
        if not go_business("buy"):
            steps.append(state_dict("open_buy_failed"))
            capture_page_state("test_page_recovery_trade_switch_open_buy_failed")
            print(json.dumps({"ok": False, "steps": steps}, ensure_ascii=False, indent=2))
            return 1
        steps.append(state_dict("buy_page"))
        sell_recovery = recover_trade_page("sell", label="trade_switch_buy_to_sell")
        steps.append(
            {
                "label": "recover_buy_to_sell",
                "recovery": {
                    "before": asdict(sell_recovery.before),
                    "after": asdict(sell_recovery.after),
                    "recovered": sell_recovery.recovered,
                    "action": sell_recovery.action,
                    "steps": sell_recovery.steps,
                },
            }
        )
        buy_recovery = recover_trade_page("buy", label="trade_switch_sell_to_buy")
        steps.append(
            {
                "label": "recover_sell_to_buy",
                "recovery": {
                    "before": asdict(buy_recovery.before),
                    "after": asdict(buy_recovery.after),
                    "recovered": buy_recovery.recovered,
                    "action": buy_recovery.action,
                    "steps": buy_recovery.steps,
                },
            }
        )
        steps.append(recovery_dict("recover_trade_switch_to_main", PageKind.MAIN_MAP, allow_go_home=True))
        final_state = classify_page()
        steps.append({"label": "final", "state": asdict(final_state)})
        ok = sell_recovery.recovered and buy_recovery.recovered and final_state.kind == PageKind.MAIN_MAP
        print(json.dumps({"ok": ok, "steps": steps}, ensure_ascii=False, indent=2))
        return 0 if ok else 1

    if not go_business("buy"):
        steps.append(state_dict("open_buy_failed"))
        capture_page_state("test_page_recovery_open_buy_failed")
        print(json.dumps({"ok": False, "steps": steps}, ensure_ascii=False, indent=2))
        return 1
    steps.append(state_dict("buy_page"))
    steps.append(recovery_dict("recover_buy_to_main", PageKind.MAIN_MAP, allow_go_home=True))

    if not go_business("sell"):
        steps.append(state_dict("open_sell_failed"))
        capture_page_state("test_page_recovery_open_sell_failed")
        print(json.dumps({"ok": False, "steps": steps}, ensure_ascii=False, indent=2))
        return 1
    steps.append(state_dict("sell_page"))
    steps.append(recovery_dict("recover_sell_to_main", PageKind.MAIN_MAP, allow_go_home=True))

    final_state = classify_page()
    steps.append({"label": "final", "state": asdict(final_state)})
    ok = final_state.kind == PageKind.MAIN_MAP
    print(json.dumps({"ok": ok, "steps": steps}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
