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


def role_catalog_names() -> list[str]:
    data = read_json(RESOURCES_PATH / "goods" / "RoleCatalog2026.json", {})
    raw_roles = data.get("roles") if isinstance(data, dict) else data
    if not isinstance(raw_roles, list):
        return configurable_role_names()

    roles: list[str] = []
    seen: set[str] = set()
    for name in raw_roles:
        role = str(name).strip()
        if not role or role in seen:
            continue
        seen.add(role)
        roles.append(role)
    return roles or configurable_role_names()


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


def configurable_role_names() -> list[str]:
    data = read_json(RESOURCES_PATH / "goods" / "ColumbaTradeData2026.json", {})
    if not isinstance(data, dict):
        return []

    roles: list[str] = []
    seen: set[str] = set()

    def add(names):
        for name in names or []:
            role = str(name).strip()
            if not role or role in seen:
                continue
            seen.add(role)
            roles.append(role)

    add((data.get("resonance_skills") or {}).keys())
    add((data.get("default_roles") or {}).keys())
    default_config = data.get("default_player_config") or {}
    add((default_config.get("roles") or {}).keys())
    return roles


def _role_level_configured(value) -> bool:
    if isinstance(value, dict):
        value = value.get("resonance")
    return value not in (None, "")


def missing_role_resonance_config() -> bool:
    return bool(missing_role_resonance_names())


def missing_role_resonance_names() -> list[str]:
    roles = role_catalog_names()
    if not roles:
        return []
    configured = cfg.tradePlannerRoleResonance.value or {}
    if not isinstance(configured, dict):
        return roles
    return [role for role in roles if not _role_level_configured(configured.get(role))]


def configured_role_resonance_names() -> list[str]:
    roles = role_catalog_names()
    if not roles:
        return []
    configured = cfg.tradePlannerRoleResonance.value or {}
    if not isinstance(configured, dict):
        return []
    return [role for role in roles if _role_level_configured(configured.get(role))]


def newly_added_missing_role_resonance_names() -> list[str]:
    roles = role_catalog_names()
    missing = missing_role_resonance_names()
    if not roles or not missing or len(missing) >= len(roles):
        return []
    if missing == roles[-len(missing) :]:
        return missing
    return []


def missing_unavailable_cities_config() -> bool:
    return not bool(cfg.tradePlannerAccountProfileReady.value)


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
    if missing_role_resonance_config():
        reasons.append("缺少乘员共振配置")
    if missing_unavailable_cities_config():
        reasons.append("需要确认城市开放状态")
    return reasons


def account_config_ready() -> bool:
    return not missing_account_config_reasons()
