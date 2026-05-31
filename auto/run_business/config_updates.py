from __future__ import annotations

from loguru import logger
from qfluentwidgets import qconfig

from app.common.account_config import account_config_auto_enabled
from app.common.config import cfg
from app.common.config_change import emit_config_changed
from core.model import app


class TradeRouteReplanRequired(RuntimeError):
    """Raised when account-derived trade config changes during a run."""


def _normalized_resonance_level(value) -> int:
    if isinstance(value, dict):
        value = value.get("resonance", -1)
    try:
        if value is None or value == "":
            return -1
        resonance = int(value)
    except (TypeError, ValueError):
        return -1
    if resonance in {-1, 0, 1, 2, 3, 4, 5}:
        return resonance
    return 5 if resonance >= 5 else -1


def _trade_product_status_values(city_name: str | None, good_name: str):
    good = str(good_name or "").strip()
    city = str(city_name or "").strip()
    keys = [f"{city}/{good}"] if city else []
    keys.append(good)
    status = dict(cfg.tradePlannerProductUnlockStatus.value or {})
    status_by_city = dict(cfg.tradePlannerProductUnlockStatusByCity.value or {})
    city_status = dict(status_by_city.get(city) or {}) if city else {}

    values: list[bool] = []
    for key in keys:
        if key in status:
            values.append(bool(status[key]))
    if city and good in city_status:
        values.append(bool(city_status[good]))
    return values


def trade_product_status_replan_needed(
    city_name: str | None,
    good_name: str,
    unlocked: bool,
) -> bool:
    """Return whether a newly observed unlock state should trigger replanning."""
    old_values = _trade_product_status_values(city_name, good_name)
    if not old_values:
        return not unlocked
    if any(value != unlocked for value in old_values):
        return True
    return False


def set_trade_product_unlock_state(
    city_name: str | None,
    good_name: str,
    unlocked: bool,
    *,
    reason: str = "交易所商品识别",
) -> tuple[bool, bool]:
    """Persist one city/product unlock state.

    Returns ``(changed, replan_needed)``. Unknown -> unlocked only records the
    scan result and does not force replanning; any transition involving a locked
    state does.
    """
    if not account_config_auto_enabled():
        logger.info(f"账号配置读取为手动模式，跳过商品解锁状态自动写回: {good_name}")
        return False, False

    good = str(good_name or "").strip()
    if not good:
        return False, False

    city = str(city_name or "").strip()
    key = f"{city}/{good}" if city else good
    unlocked = bool(unlocked)
    replan_needed = trade_product_status_replan_needed(city, good, unlocked)

    status = dict(cfg.tradePlannerProductUnlockStatus.value or {})
    status_by_city = dict(cfg.tradePlannerProductUnlockStatusByCity.value or {})
    city_status = dict(status_by_city.get(city) or {}) if city else {}

    changed = False
    if city:
        if city_status.get(good) is not unlocked:
            city_status[good] = unlocked
            status_by_city[city] = city_status
            changed = True

    if unlocked:
        for status_key in (key, good):
            if status.get(status_key) is False:
                status.pop(status_key, None)
                changed = True
    elif status.get(key) is not False:
        status[key] = False
        changed = True

    if not changed:
        return False, False

    qconfig.set(cfg.tradePlannerProductUnlockStatus, status)
    qconfig.set(cfg.tradePlannerProductUnlockStatusByCity, status_by_city)
    try:
        app.TradePlanner.ProductUnlockStatus = status
        app.TradePlanner.ProductUnlockStatusByCity = status_by_city
    except Exception as exc:
        logger.debug(f"同步运行时商品解锁配置失败: {exc}")

    state_text = "已解锁" if unlocked else "未解锁"
    logger.info(f"已自动记录商品解锁状态: {key}={state_text} ({reason})")
    if replan_needed:
        emit_config_changed(
            "跑商配置已自动更新",
            f"{key} 已识别为{state_text}，将重新规划路线。",
        )
    return True, replan_needed


def update_trade_account_profile(
    *,
    cargo_capacity: int | None = None,
    prestige_by_city: dict[str, int] | None = None,
    role_resonance: dict[str, int] | None = None,
    unavailable_cities: list[str] | None = None,
    reason: str = "账号配置读取",
) -> list[str]:
    """Update account-derived planner config in auto mode."""
    if not account_config_auto_enabled():
        logger.info(f"账号配置读取为手动模式，跳过账号配置自动写回: {reason}")
        return []

    updates: list[str] = []
    if cargo_capacity is not None and int(cargo_capacity) > 0:
        if int(cfg.tradePlannerMaxLot.value or 0) != int(cargo_capacity):
            qconfig.set(cfg.tradePlannerMaxLot, int(cargo_capacity))
            updates.append(f"货舱 {cargo_capacity}")

    if prestige_by_city:
        prestige = dict(cfg.tradePlannerPrestigeByCity.value or {})
        changed_count = 0
        for city, level in prestige_by_city.items():
            city_name = str(city).strip()
            if not city_name:
                continue
            old_level = prestige.get(city_name)
            new_level = int(level)
            if old_level is None or new_level > int(old_level or 0):
                prestige[city_name] = new_level
                changed_count += 1
        if changed_count:
            qconfig.set(cfg.tradePlannerPrestigeByCity, prestige)
            updates.append(f"声望 {changed_count}城")

    if role_resonance:
        recognized_roles: dict[str, int] = {}
        for role, level in role_resonance.items():
            role_name = str(role).strip()
            if not role_name:
                continue
            recognized_roles[role_name] = _normalized_resonance_level(level)
        old_roles = {
            str(role).strip(): _normalized_resonance_level(value)
            for role, value in dict(cfg.tradePlannerRoleResonance.value or {}).items()
            if str(role).strip()
        }
        merged_roles = dict(old_roles)
        changed_count = 0
        for role, level in recognized_roles.items():
            if merged_roles.get(role) == level:
                continue
            merged_roles[role] = level
            changed_count += 1
        if changed_count:
            qconfig.set(cfg.tradePlannerRoleResonance, merged_roles)
            updates.append(f"乘员共振 {changed_count}项，已记录 {len(merged_roles)}人")

    if unavailable_cities is not None:
        normalized_unavailable = sorted(
            {str(city).strip() for city in unavailable_cities if str(city).strip()}
        )
        old_unavailable = sorted(
            {
                str(city).strip()
                for city in (cfg.tradePlannerUnavailableCities.value or [])
                if str(city).strip()
            }
        )
        if normalized_unavailable != old_unavailable:
            qconfig.set(cfg.tradePlannerUnavailableCities, normalized_unavailable)
            include_cities = [
                city
                for city in (cfg.tradePlannerIncludeCities.value or [])
                if city not in normalized_unavailable
            ]
            if include_cities != list(cfg.tradePlannerIncludeCities.value or []):
                qconfig.set(cfg.tradePlannerIncludeCities, include_cities)
            updates.append(f"未开放城市 {len(normalized_unavailable)}个")

    if cargo_capacity is not None or prestige_by_city or role_resonance or unavailable_cities is not None:
        qconfig.set(cfg.tradePlannerAccountProfileReady, True)
        try:
            app.TradePlanner.AccountProfileReady = True
            app.TradePlanner.MaxLot = cfg.tradePlannerMaxLot.value
            app.TradePlanner.PrestigeByCity = dict(
                cfg.tradePlannerPrestigeByCity.value or {}
            )
            app.TradePlanner.RoleResonance = dict(
                cfg.tradePlannerRoleResonance.value or {}
            )
            app.TradePlanner.UnavailableCities = list(
                cfg.tradePlannerUnavailableCities.value or []
            )
            app.TradePlanner.IncludeCities = list(cfg.tradePlannerIncludeCities.value or [])
        except Exception as exc:
            logger.debug(f"同步运行时账号配置失败: {exc}")

    if updates:
        logger.info(f"已自动更新账号配置: {', '.join(updates)} ({reason})")
        emit_config_changed(
            "账号配置已自动更新",
            "，".join(updates),
        )
    return updates


def disable_trade_product_for_city(
    city_name: str | None,
    good_name: str,
    *,
    reason: str = "购买时检测到未解锁",
) -> bool:
    """Mark one product as locked for a city so future planning skips it."""
    changed, replan_needed = set_trade_product_unlock_state(
        city_name,
        good_name,
        False,
        reason=reason,
    )
    if changed:
        city = str(city_name or "").strip()
        key = f"{city}/{good_name}" if city else str(good_name)
        logger.warning(f"已自动标记未解锁商品: {key} ({reason})")
    return replan_needed


def enable_trade_product_for_city(
    city_name: str | None,
    good_name: str,
    *,
    reason: str = "购买成功",
) -> bool:
    """Remove a locked-product override when a product is confirmed purchasable."""
    changed, replan_needed = set_trade_product_unlock_state(
        city_name,
        good_name,
        True,
        reason=reason,
    )
    if changed:
        city = str(city_name or "").strip()
        key = f"{city}/{good_name}" if city else str(good_name)
        logger.info(f"已自动恢复商品解锁状态: {key} ({reason})")
    return replan_needed
