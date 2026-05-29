from dataclasses import dataclass

from loguru import logger
from qfluentwidgets import qconfig

from app.common.config import cfg
from app.common.runtime_status import emit_run_status
from core.control.control import screenshot
from core.module.bgr import BGR
from core.preset.control import click, ocr_click, wait_gbr


@dataclass(frozen=True)
class StrengthResource:
    name: str
    restore: int
    count_config: object
    use_all_config: object
    fallback: str | None = None


MEDICINE_RESOURCES = (
    StrengthResource("提神棒棒糖", 60, cfg.RunStrengthLollipopCount, cfg.RunStrengthLollipopUseAll, "candy"),
    StrengthResource("提神口香糖", 100, cfg.RunStrengthGumCount, cfg.RunStrengthGumUseAll),
    StrengthResource("仙人掌提神跳糖", 900, cfg.RunStrengthCactusCandyCount, cfg.RunStrengthCactusCandyUseAll),
)
HUASHI_RESOURCE = StrengthResource("桦石", 150, cfg.RunHuashiCount, cfg.RunHuashiUseAll)


def check_shop_strength():
    image = screenshot()
    image.crop_image((959, 13), (1036, 38))
    text = image.ocr()
    if len(text) == 0:
        return True
    strength = text[0]["text"].split("/")
    cur_strength = int(strength[0])
    total__strength = int(strength[1])
    return total__strength - cur_strength > 60


def has_configured_strength_recovery() -> bool:
    if bool(cfg.RunAllowFood.value):
        return True
    if bool(cfg.RunUseStrengthMedicine.value):
        for resource in MEDICINE_RESOURCES:
            if _resource_available(resource):
                return True
    if bool(cfg.RunUseHuashi.value) and _resource_available(HUASHI_RESOURCE):
        return True
    return bool(cfg.RunAllowDrink.value)


def _resource_available(resource: StrengthResource) -> bool:
    return bool(resource.use_all_config.value) or int(resource.count_config.value or 0) > 0


def _consume_resource_count(resource: StrengthResource) -> None:
    if bool(resource.use_all_config.value):
        return
    count = max(0, int(resource.count_config.value or 0) - 1)
    qconfig.set(resource.count_config, count)


def open_strength_page() -> bool:
    click((974, 32))
    return wait_gbr(
        (522, 110),
        BGR(30, 40, 105),
        BGR(40, 50, 115),
        cropped_pos1=(482, 92),
        cropped_pos2=(562, 134),
    )

def use_food():
    click((1107, 606))
    if not wait_gbr(
        (61, 130),
        BGR(26, 38, 91),
        BGR(26, 38, 91)
    ):
        logger.error("未找到便当页面")
        return False
    click((1077, 430))
    status = ocr_click("确认", cropped_pos1=(952, 485), cropped_pos2=(1022, 522))
    click((1077, 430))
    return status


def use_candy():
    click((655, 242))
    return ocr_click("补充", cropped_pos1=(952, 565), cropped_pos2=(1023, 602))


def use_named_strength_resource(resource: StrengthResource) -> bool:
    if not _resource_available(resource):
        return False
    emit_run_status("正在恢复疲劳", f"尝试使用 {resource.name}（{resource.restore}疲劳）")
    if resource.fallback == "candy":
        ok = use_candy()
    else:
        ok = ocr_click(resource.name, cropped_pos1=(430, 90), cropped_pos2=(1120, 620), log=False)
        if ok:
            ok = ocr_click("补充", cropped_pos1=(930, 500), cropped_pos2=(1045, 630), trynum=4, log=False)
            if not ok:
                ok = ocr_click("确认", cropped_pos1=(930, 480), cropped_pos2=(1045, 630), trynum=2, log=False)
    if ok:
        _consume_resource_count(resource)
        logger.info(f"已使用疲劳恢复资源: {resource.name}")
    return ok


def use_huashi() -> bool:
    return use_named_strength_resource(HUASHI_RESOURCE)


def use_drink_if_available() -> bool:
    # Drinking requires city-specific shop/menu navigation. Keep the config and
    # recovery slot wired, but avoid speculative taps until the UI path is calibrated.
    logger.warning("喝酒恢复疲劳暂未接入具体城市入口，跳过")
    return False


def recover_strength_by_config() -> bool:
    if not has_configured_strength_recovery():
        logger.info("未启用任何疲劳恢复资源，停止跑商")
        return False
    if not open_strength_page():
        logger.error("未找到体力页面")
        return False

    if bool(cfg.RunAllowFood.value):
        emit_run_status("正在恢复疲劳", "体力不足，优先尝试便当柜")
        if use_food():
            logger.info("已使用便当恢复疲劳")
            return True

    if bool(cfg.RunUseStrengthMedicine.value):
        for resource in MEDICINE_RESOURCES:
            if use_named_strength_resource(resource):
                return True

    if bool(cfg.RunUseHuashi.value) and use_huashi():
        return True

    if bool(cfg.RunAllowDrink.value) and use_drink_if_available():
        return True

    logger.error("已按疲劳配置尝试恢复，但没有成功恢复疲劳")
    return False


def use_strength():
    return recover_strength_by_config()
