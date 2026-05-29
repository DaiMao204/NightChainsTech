"""
Author: Night-stars-1 nujj1042633805@gmail.com
Date: 2024-04-06 23:29:48
LastEditTime: 2024-04-19 13:24:00
LastEditors: Night-stars-1 nujj1042633805@gmail.com
"""

import inspect
from PySide6.QtCore import QThread, Signal
from loguru import logger

from app.common.runtime_status import emit_run_status
from core.exception.exceptions import StopExecution

from ..common.config import cfg


class Worker(QThread):
    result = Signal(object)

    def __init__(self, func, stop = lambda : None, **kwargs):
        super(Worker, self).__init__()
        self.func = func
        self.stop_func = stop
        self.kwargs = kwargs

    def run(self):
        try:
            result = self.func(**self.kwargs)
            self.result.emit(result)
        except StopExecution:
            emit_run_status("已停止", "任务已收到停止请求")
            pass
        except AssertionError as e:
            logger.error(f"{e}")
            emit_run_status("运行异常", str(e))
        except Exception:
            logger.exception("崩溃信息:")
            emit_run_status("运行异常", "脚本执行时发生异常，已保存诊断信息")

    def stop(self):
        self.stop_func()

class UpdateWorker(QThread):
    result = Signal(object)
    progress_changed = Signal(int)
    update_finished = Signal(bool)

    def __init__(self, func, **kwargs):
        super(UpdateWorker, self).__init__()
        self.func = func
        self.kwargs = kwargs
        # 检查函数是否接受update_progress参数
        sig = inspect.signature(func)
        if "progress_changed" in sig.parameters and "progress_changed" not in kwargs:
            self.kwargs["progress_changed"] = self.progress_changed.emit
        if "update_finished" in sig.parameters and "update_finished" not in kwargs:
            self.kwargs["update_finished"] = self.update_finished.emit

    def run(self):
        try:
            result = self.func(**self.kwargs)
            self.result.emit(result)
            self.update_finished.emit(True)
        except StopExecution:
            emit_run_status("已停止", "任务已收到停止请求")
            self.update_finished.emit(False)
        except AssertionError as e:
            logger.error(f"{e}")
            emit_run_status("运行异常", str(e))
            self.update_finished.emit(False)
        except Exception:
            logger.exception("崩溃信息:")
            emit_run_status("运行异常", "脚本执行时发生异常，已保存诊断信息")
            self.update_finished.emit(False)
