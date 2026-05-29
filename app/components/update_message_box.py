from __future__ import annotations

from PySide6.QtWidgets import QApplication
from loguru import logger
from qfluentwidgets import BodyLabel, MessageBoxBase, ProgressBar, SubtitleLabel

from app.utils.worker import UpdateWorker
from core.utils.update.manifest_update_utils import (
    ManifestUpdateInfo,
    ManifestUpdateUtils,
    PreparedUpdate,
)


class UpdateMessageBox(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.update_utils = ManifestUpdateUtils()
        self.manifest: ManifestUpdateInfo | None = None
        self.prepared: PreparedUpdate | None = None

        self.titleLabel = SubtitleLabel("发现新版本", self)
        self.bodyLabel = BodyLabel(self)
        self.progressBar = ProgressBar(self)
        self.progressBar.setValue(0)
        self.progressBar.hide()

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.bodyLabel)
        self.viewLayout.addWidget(self.progressBar)

        self.yesButton.setText("立即更新")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(420)

    def show_update(self, manifest: ManifestUpdateInfo):
        self.manifest = manifest
        self.prepared = None
        self.progressBar.setValue(0)
        self.progressBar.hide()
        self.yesButton.setEnabled(True)
        self.cancelButton.setEnabled(True)
        self.titleLabel.setText(f"发现新版本 {manifest.version}")
        notes = manifest.notes or "该版本没有填写更新说明。"
        size = f"\n\n大小：{manifest.size} 字节" if manifest.size else ""
        asset = f"\n\n更新包：{manifest.asset_name}" if manifest.asset_name else ""
        verify = "" if manifest.sha256 else "\n\n该 Release 未提供 SHA256，更新时将跳过完整性校验。"
        force = "\n\n这是一个强制更新。" if manifest.force else ""
        self.bodyLabel.setText(f"{notes}{asset}{size}{verify}{force}")
        try:
            self.yesButton.clicked.disconnect()
        except RuntimeError:
            pass
        self.yesButton.clicked.connect(self.update)
        super().show()

    def update(self):
        if not self.manifest:
            return
        self.titleLabel.setText("正在下载更新")
        self.bodyLabel.setText("下载并校验更新包，完成后程序会自动重启。")
        self.progressBar.show()
        self.yesButton.setEnabled(False)
        self.cancelButton.setEnabled(False)

        self.worker = UpdateWorker(self.update_utils.prepare_update, manifest=self.manifest)
        self.worker.progress_changed.connect(self.progressBar.setValue)
        self.worker.result.connect(self.on_prepared)
        self.worker.update_finished.connect(self.on_update_finished)
        self.worker.start()

    def on_prepared(self, prepared: PreparedUpdate):
        self.prepared = prepared
        self.progressBar.setValue(100)
        self.titleLabel.setText("准备重启")
        self.bodyLabel.setText("更新包已校验通过，正在启动独立更新程序。")

    def on_update_finished(self, ok: bool):
        if not ok or not self.prepared:
            self.titleLabel.setText("更新失败")
            self.bodyLabel.setText("下载、校验或准备更新失败，请稍后重试。")
            self.yesButton.setEnabled(True)
            self.cancelButton.setEnabled(True)
            return
        try:
            self.update_utils.launch_updater(self.prepared)
        except Exception as exc:
            logger.exception(f"启动更新程序失败: {exc}")
            self.titleLabel.setText("启动更新程序失败")
            self.bodyLabel.setText(str(exc))
            self.yesButton.setEnabled(True)
            self.cancelButton.setEnabled(True)
            return
        app = QApplication.instance()
        if app:
            app.quit()
