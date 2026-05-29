from __future__ import annotations

from typing import Any


def format_profit_status(status: dict[str, Any]) -> str:
    reference_profit = status.get("reference_profit")
    if reference_profit is None:
        reference_profit = status.get("general_profit_index")

    mixed_currency_profit = bool(status.get("mixed_currency_profit"))
    jiaozi_profit = status.get("jiaozi_profit")
    tiemeng_profit = status.get("tiemeng_profit")
    if jiaozi_profit is not None and tiemeng_profit is not None:
        mixed_currency_profit = True

    total_profit = status.get("total_profit")
    if total_profit is None and not mixed_currency_profit:
        total_profit = status.get("profit")

    lines: list[str] = []
    if reference_profit is not None:
        label = str(status.get("reference_profit_label") or "综合参考利润")
        line = f"{label}：{reference_profit}"
        jiaozi_index = status.get("jiaozi_general_profit_index")
        tiemeng_index = status.get("tiemeng_general_profit_index")
        if jiaozi_index is not None and tiemeng_index is not None:
            line += f"（交子{jiaozi_index}/铁盟币{tiemeng_index}）"
        lines.append(line)

    if mixed_currency_profit and jiaozi_profit is not None and tiemeng_profit is not None:
        lines.append(f"总利润：交子{jiaozi_profit}/铁盟币{tiemeng_profit}")
    elif total_profit is not None:
        line = f"总利润：{total_profit}"
        if jiaozi_profit is not None and tiemeng_profit is not None:
            line += f"（交子{jiaozi_profit}/铁盟币{tiemeng_profit}）"
        lines.append(line)

    return "\n".join(lines)
