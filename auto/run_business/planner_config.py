from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from core.utils.utils import ROOT_PATH, read_json

from .planner import (
    RoutePlanOptions,
    normalize_city_pairs,
    normalize_mixed_currency_priority,
)

DEFAULT_TRADE_PLANNER_CONFIG_PATH = ROOT_PATH / "config" / "trade_planner.json"


def load_trade_planner_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else DEFAULT_TRADE_PLANNER_CONFIG_PATH
    if not config_path.exists():
        return {}
    payload = read_json(config_path)
    if not isinstance(payload, dict):
        return {}
    return payload.get("TradePlanner", payload) if isinstance(payload.get("TradePlanner"), dict) else payload


def _first(raw: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in raw:
            return raw[key]
    return default


def _set(value: Any) -> set[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        values = [item.strip() for item in value.split(",")]
    else:
        values = [str(item).strip() for item in value]
    result = {item for item in values if item}
    return result or None


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "已解锁", "解锁", "开启"}
    return bool(value)


def _int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _roles(value: dict[str, Any] | None) -> dict[str, dict[str, int]] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, dict[str, int]] = {}
    for role_name, role_value in value.items():
        if isinstance(role_value, dict):
            resonance = int(role_value.get("resonance") or 0)
        else:
            resonance = int(role_value or 0)
        if resonance <= 0:
            resonance = 0
        elif resonance < 4:
            resonance = 1
        elif resonance > 5:
            resonance = 5
        result[str(role_name)] = {"resonance": resonance}
    return result


def _bool_mapping(value: Any) -> dict[str, bool] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): _bool(item) for key, item in value.items()}


def _nested_bool_mapping(value: Any) -> dict[str, dict[str, bool]] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, dict[str, bool]] = {}
    for city, goods in value.items():
        if isinstance(goods, dict):
            result[str(city)] = {str(good): _bool(unlocked) for good, unlocked in goods.items()}
    return result or None


def route_plan_options_from_config(
    raw_config: dict[str, Any],
    base: RoutePlanOptions | None = None,
) -> RoutePlanOptions:
    options = base or RoutePlanOptions()
    if not raw_config:
        return options
    raw = raw_config.get("TradePlanner", raw_config) if isinstance(raw_config.get("TradePlanner"), dict) else raw_config

    bargain = _first(raw, "bargain", "Bargain", default={}) or {}
    onegraph = _first(raw, "onegraph", "Onegraph", default={}) or {}

    updates: dict[str, Any] = {}
    if (
        value := _first(
            raw,
            "MixedCurrencyPriority",
            "mixedCurrencyPriority",
            "CurrencyPriority",
            "currencyPriority",
            "WulinyuanPriority",
            "wulinyuanPriority",
            "JiaoziPriority",
            "jiaoziPriority",
        )
    ) is not None:
        updates["mixed_currency_priority"] = normalize_mixed_currency_priority(value)
    if (value := _first(raw, "MaxLot", "maxLot")) is not None:
        updates["max_goods_num"] = _int(value)
    if (value := _first(raw, "MaxRestock", "maxRestock", default=onegraph.get("maxRestock"))) is not None:
        updates["max_restock"] = _int(value)
    if (value := _first(raw, "BargainPercent", "bargainPercent", default=bargain.get("bargainPercent"))) is not None:
        updates["bargain_percent"] = _int(value)
    if (value := _first(raw, "RaisePercent", "raisePercent", default=bargain.get("raisePercent"))) is not None:
        updates["raise_percent"] = _int(value)
    if (value := _first(raw, "BargainFatigue", "bargainFatigue", default=bargain.get("bargainFatigue"))) is not None:
        updates["bargain_fatigue"] = _int(value)
    if (value := _first(raw, "RaiseFatigue", "raiseFatigue", default=bargain.get("raiseFatigue"))) is not None:
        updates["raise_fatigue"] = _int(value)
    if (value := _first(raw, "CompareNoReturnBargain", "compareNoReturnBargain")) is not None:
        updates["compare_no_return_bargain"] = _bool(value)
    if (value := _first(raw, "AutoHaggle", "autoHaggle", "UsePlannerHaggle", "usePlannerHaggle")) is not None:
        updates["auto_haggle"] = _bool(value)
    if (value := _first(raw, "DefaultPrestigeLevel", "defaultPrestigeLevel")) is not None:
        updates["default_prestige_level"] = _int(value)
    if (value := _first(raw, "PrestigeByCity", "prestige", "prestigeByCity")) is not None:
        updates["prestige_by_city"] = {str(city): int(level) for city, level in dict(value).items()}
    if (value := _first(raw, "RoleResonance", "roles", "roleResonance")) is not None:
        updates["roles"] = _roles(value)
    if (value := _first(raw, "UseDefaultRoles", "useDefaultRoles")) is not None:
        updates["use_default_roles"] = _bool(value)
    if (value := _first(raw, "DisabledRoles", "disabledRoles")) is not None:
        updates["disabled_roles"] = _set(value)
    if (value := _first(raw, "ProductUnlockStatus", "productUnlockStatus")) is not None:
        updates["product_unlock_status"] = _bool_mapping(value)
    if (value := _first(raw, "ProductUnlockStatusByCity", "productUnlockStatusByCity")) is not None:
        updates["product_unlock_status_by_city"] = _nested_bool_mapping(value)
    if (value := _first(raw, "Events", "events")) is not None:
        updates["events"] = dict(value)
    if (value := _first(raw, "IncludeCities", "includeCities")) is not None:
        updates["include_cities"] = _set(value)
    if (value := _first(raw, "ExcludeCities", "excludeCities")) is not None:
        updates["exclude_cities"] = _set(value)
    if (value := _first(raw, "AllowedGoods", "allowedGoods")) is not None:
        updates["allowed_goods"] = _set(value)
    blocked_goods = _set(_first(raw, "BlockedGoods", "blockedGoods", "ErrorItemList", "errorItemList"))
    if blocked_goods is not None:
        updates["blocked_goods"] = blocked_goods
    if (value := _first(raw, "AllowedCityPairs", "allowedCityPairs", "CityPairs", "cityPairs")) is not None:
        updates["allowed_city_pairs"] = normalize_city_pairs(value)
    if (value := _first(raw, "BlockedCityPairs", "blockedCityPairs")) is not None:
        updates["blocked_city_pairs"] = normalize_city_pairs(value)

    return replace(options, **{key: value for key, value in updates.items() if value is not None})
