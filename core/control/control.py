"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-03-20 22:24:35
LastEditTime: 2025-02-11 16:56:45
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

import random
import time
from typing import Optional, Tuple

import cv2 as cv
import numpy as np
from adb_shell.adb_device import AdbDeviceTcp
from loguru import logger

from app.common.runtime_status import emit_run_status
from core.control.adb import ADB
from core.control.adb_port import EmulatorType
from core.control.base_control import IADB
from core.control.nemu import NEMU
from core.exception.exceptions import StopExecution
from core.image.image import Image
from core.model import app

EXCURSIONX = [-10, 10]
EXCURSIONY = [-10, 10]
STOP = False
GAME_PACKAGE = "com.hermes.goda"
GAME_LAUNCH_TIMEOUT = 25.0

control: IADB = ADB()


def connect(adb_port: Optional[int] = None, *, ensure_game: bool = True):
    """
    连接ADB

    :param order: ADB端口
    """
    global control, STOP
    STOP = False
    device = app.Global.device
    if device.is_mumu:
        if ensure_game:
            ensure_game_app_running(adb_port=adb_port)
        control = NEMU()
        status = control.connect(adb_port)
        if status:
            return status
        else:
            logger.warning("MUMUIPC连接失败，尝试使用ADB连接")
    control = ADB()
    status = control.connect(adb_port)
    if status and ensure_game:
        status = ensure_game_app_running(adb_port=adb_port)
    return status


def stop():
    global STOP
    STOP = True


def kill():
    """
    关闭连接
    """
    control.kill()


def adb_shell(command: str, adb_port: Optional[int] = None) -> str:
    """Run one ADB shell command on the configured emulator."""
    device = getattr(control, "device", None)
    shell = getattr(device, "shell", None)
    if callable(shell):
        try:
            return shell(command)
        except Exception as exc:
            logger.debug(f"当前ADB连接执行shell失败，尝试新连接: {exc}")

    port = adb_port if adb_port is not None else app.Global.device.port
    if port is None:
        raise RuntimeError("未配置ADB端口，无法执行ADB shell命令")

    adb = AdbDeviceTcp("127.0.0.1", port=port)
    status = adb.connect()
    if not status:
        raise RuntimeError(f"ADB连接失败: 127.0.0.1:{port}")
    try:
        return adb.shell(command)
    finally:
        adb.close()


def get_foreground_package(adb_port: Optional[int] = None) -> str | None:
    """Return the current foreground Android package when it can be detected."""
    try:
        output = adb_shell("dumpsys window", adb_port=adb_port)
    except Exception as exc:
        logger.debug(f"读取前台应用失败: {exc}")
        return None

    for line in output.splitlines():
        if "mCurrentFocus" not in line and "mFocusedApp" not in line:
            continue
        for token in line.replace("}", " ").replace("{", " ").split():
            if "/" not in token:
                continue
            package = token.split("/", 1)[0]
            if "." in package:
                return package
    return None


def launch_game_app(
    package: str = GAME_PACKAGE,
    *,
    adb_port: Optional[int] = None,
) -> bool:
    """Launch the game package without force-stopping an already running process."""
    logger.warning(f"启动游戏应用: {package}")
    emit_run_status("正在启动游戏", "检测到游戏未打开，正在启动游戏")
    adb_shell(
        f"monkey -p {package} -c android.intent.category.LAUNCHER 1",
        adb_port=adb_port,
    )
    return True


def ensure_game_app_running(
    package: str = GAME_PACKAGE,
    *,
    adb_port: Optional[int] = None,
    timeout: float = GAME_LAUNCH_TIMEOUT,
) -> bool:
    """Ensure the target game is the foreground Android app before automation runs."""
    current_package = get_foreground_package(adb_port=adb_port)
    if current_package == package:
        return True

    if current_package:
        logger.info(f"当前前台应用不是游戏: {current_package}")
    try:
        launch_game_app(package, adb_port=adb_port)
    except Exception as exc:
        logger.error(f"启动游戏失败: {exc}")
        emit_run_status("启动游戏失败", "无法自动启动游戏，请确认模拟器已打开")
        return False

    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        time.sleep(1.0)
        current_package = get_foreground_package(adb_port=adb_port)
        if current_package == package:
            emit_run_status("游戏已启动", "游戏已打开，正在继续执行")
            return True

    logger.error(f"等待游戏启动超时: {package}")
    emit_run_status("启动游戏超时", "未检测到游戏进入前台，请确认模拟器状态")
    return False


def restart_game_app(
    package: str = GAME_PACKAGE,
    *,
    adb_port: Optional[int] = None,
    launch_wait: float = 8.0,
) -> bool:
    """Force stop and relaunch the game package."""
    logger.warning(f"重启游戏应用: {package}")
    adb_shell(f"am force-stop {package}", adb_port=adb_port)
    time.sleep(2.0)
    adb_shell(
        f"monkey -p {package} -c android.intent.category.LAUNCHER 1",
        adb_port=adb_port,
    )
    time.sleep(launch_wait)
    return True


def input_swipe(pos1=(919, 617), pos2=(919, 908), swipe_time: int = 100):
    """
    滑动屏幕(可超出屏幕)

    :param pos1: 坐标1
    :param pos2: 坐标2
    :param time: 操作时间(毫秒)
    """
    num = 0
    # 添加随机值
    pos_x1 = control.ratio * pos1[0] + random.randint(*EXCURSIONX)
    pos_y1 = control.ratio * pos1[1] + random.randint(*EXCURSIONY)
    pos_x2 = control.ratio * pos2[0] + random.randint(*EXCURSIONX)
    pos_y2 = control.ratio * pos2[1] + random.randint(*EXCURSIONY)

    logger.debug(f"滑动 ({pos_x1}, {pos_y1}) -> ({pos_x2}, {pos_y2})")
    while abs(pos_x2 - pos_x1) > 10 or abs(pos_y2 - pos_y1) > 10:
        if num >= 1:
            time.sleep(0.5)
        limit_pos_x1 = max(control.safe_area[0], min(pos_x1, control.safe_area[2]))
        limit_pos_y1 = max(control.safe_area[1], min(pos_y1, control.safe_area[3]))
        limit_pos_x2 = max(control.safe_area[0], min(pos_x2, control.safe_area[2]))
        limit_pos_y2 = max(control.safe_area[1], min(pos_y2, control.safe_area[3]))
        logger.debug(
            f"多次滑动 ({limit_pos_x1}, {limit_pos_y1}) -> ({limit_pos_x2}, {limit_pos_y2})"
        )

        control.input_swipe(
            limit_pos_x1, limit_pos_y1, limit_pos_x2, limit_pos_y2, swipe_time
        )

        # 减去当前执行的距离
        pos_x1 -= limit_pos_x1 - limit_pos_x2
        pos_y1 -= limit_pos_y1 - limit_pos_y2
        num += 1


def input_tap(pos: Tuple[int, int] = (880, 362)):
    """
    点击坐标

    :param pos: 坐标
    """
    control.input_tap(
        int(control.ratio * pos[0] + random.randint(*EXCURSIONX)), int(control.ratio * pos[1] + random.randint(*EXCURSIONY))
    )


def screenshot() -> Image:
    """
    截图
    """
    if STOP:
        raise StopExecution()

    screenshot = screenshot_image()

    return Image(screenshot)


def screenshot_image() -> cv.typing.MatLike:
    """
    截图并返回图片对象
    """
    if STOP:
        raise StopExecution()

    screenshot = control.screenshot()
    screenshot = cv.resize(screenshot, control.dsize, interpolation=cv.INTER_AREA)
    return screenshot

def wait_stopped(threshold=7100000):
    """
    等待画面静止
    参数:
        :param threshold: 参数阈值
    """
    logger.info("等待图像静止")
    while True:
        gray1 = cv.cvtColor(screenshot_image(), cv.COLOR_BGR2GRAY)
        # 等待画面变动，并再次截图
        time.sleep(0.5)
        gray2 = cv.cvtColor(screenshot_image(), cv.COLOR_BGR2GRAY)

        # 计算两帧之间的绝对差异
        diff = cv.absdiff(gray1, gray2)

        # 计算差异值
        diff_sum: int = np.sum(diff)  # type: ignore
        logger.debug(f"画面差异 {diff_sum}")

        if diff_sum < threshold:
            break
        time.sleep(1)
