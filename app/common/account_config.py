from __future__ import annotations

from app.common.config import cfg
from core.utils.utils import RESOURCES_PATH, read_json

ACCOUNT_CONFIG_AUTO = "auto"
ACCOUNT_CONFIG_MANUAL = "manual"
ACCOUNT_CONFIG_MODES = {ACCOUNT_CONFIG_AUTO, ACCOUNT_CONFIG_MANUAL}


def account_config_mode() -> str:
    mode = str(cfg.tradePlannerAccountConfigMode.value or ACCOUNT_CONFIG_AUTO)
    return mode if mode in ACCOUNT_CONFIG_MODES else ACCOUNT_CONFIG_AUTO


def account_config_auto_enabled() -> bool:
    return account_config_mode() == ACCOUNT_CONFIG_AUTO


def prestige_master_city(city: str) -> str:
    attached = read_json(RESOURCES_PATH / "goods" / "AttachedToCityData.json", {})
    if isinstance(attached, dict):
        return str(attached.get(city) or city)
    return city


def required_prestige_cities() -> list[str]:
    data = read_json(RESOURCES_PATH / "goods" / "CityPrestigeThresholds2026.json", {})
    cities = data.get("cities") if isinstance(data, dict) else {}
    if not isinstance(cities, dict):
        return []

    result: list[str] = []
    for city in cities.keys():
        master = prestige_master_city(str(city).strip())
        if master and master not in result:
            result.append(master)
    return result


def missing_prestige_cities() -> list[str]:
    prestige_by_city = cfg.tradePlannerPrestigeByCity.value or {}
    if not isinstance(prestige_by_city, dict):
        return required_prestige_cities()

    configured_cities = {
        prestige_master_city(str(city).strip())
        for city, level in prestige_by_city.items()
        if str(city).strip() and level not in (None, "")
    }
    return [city for city in required_prestige_cities() if city not in configured_cities]


def missing_account_config_reasons() -> list[str]:
    if not account_config_auto_enabled():
        return []

    reasons: list[str] = []
    if int(cfg.tradePlannerMaxLot.value or 0) <= 0:
        reasons.append("缺少货舱数量")

    missing_cities = missing_prestige_cities()
    if missing_cities:
        preview = "、".join(missing_cities[:5])
        if len(missing_cities) > 5:
            preview += f" 等 {len(missing_cities)} 个城市"
        reasons.append(f"缺少主城声望：{preview}")
    return reasons


def account_config_ready() -> bool:
    return not missing_account_config_reasons()
