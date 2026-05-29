from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from enum import Enum
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import requests
from loguru import logger
from pydantic import BaseModel, Field

from core.utils.utils import ROOT_PATH, TEMP_PATH
from version import __version__


DEFAULT_UPDATE_DIR = TEMP_PATH / "update"
DEFAULT_PRESERVE_PATHS = ("config", "logs", "cache", "diagnostics", "temp")
DEFAULT_GITHUB_REPO = "DaiMao204/NightChainsTech"
DEFAULT_GITHUB_RELEASE_API = "https://api.github.com/repos/{repo}/releases/latest"
GITHUB_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "NightChainsTech-Updater",
}


class UpdateStatus(Enum):
    LATEST = 1
    UPDATE = 2
    FAILED = 0


class ManifestUpdateInfo(BaseModel):
    version: str
    url: str
    sha256: str = ""
    size: Optional[int] = None
    notes: str = ""
    force: bool = False
    min_version: Optional[str] = None
    channel: str = "stable"
    title: Optional[str] = None
    source: str = "manifest"
    asset_name: Optional[str] = None


class PreparedUpdate(BaseModel):
    manifest: ManifestUpdateInfo
    package_path: str
    updater_command: list[str]
    restart_args: list[str] = Field(default_factory=list)


def _version_parts(version: str) -> tuple[int, ...] | None:
    parts = []
    for part in version.strip().lstrip("vV").split("."):
        if not part.isdigit():
            return None
        parts.append(int(part))
    return tuple(parts) if parts else None


def compare_versions(left: str, right: str) -> int:
    left_parts = _version_parts(left)
    right_parts = _version_parts(right)
    if left_parts is None or right_parts is None:
        return (left > right) - (left < right)
    width = max(len(left_parts), len(right_parts))
    left_parts += (0,) * (width - len(left_parts))
    right_parts += (0,) * (width - len(right_parts))
    return (left_parts > right_parts) - (left_parts < right_parts)


def is_development_version(version: str) -> bool:
    return version.strip().lower() in {"", "debug", "dev", "development", "local"}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_from_url_or_file(url: str, timeout: float) -> dict:
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        path = Path(parsed.path if parsed.scheme == "file" else url)
        return json.loads(path.read_text(encoding="utf-8"))
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _asset_score(asset: dict[str, Any]) -> tuple[int, int]:
    name = str(asset.get("name") or "").lower()
    if not name.endswith(".zip"):
        return (-1000, 0)
    score = 0
    if (
        "nightchainstech" in name
        or "night_chains_tech" in name
        or "night-chains-tech" in name
        or "黑月科技" in name
    ):
        score += 50
    if "full" in name or "windows" in name or "win" in name:
        score += 10
    if "update" in name or "patch" in name or "increment" in name:
        score -= 40
    if "source" in name:
        score -= 100
    return (score, int(asset.get("size") or 0))


def select_github_release_asset(release: dict[str, Any]) -> dict[str, Any]:
    assets = [asset for asset in release.get("assets") or [] if isinstance(asset, dict)]
    candidates = [asset for asset in assets if _asset_score(asset)[0] > -1000]
    if not candidates:
        raise ValueError("GitHub Release 中未找到 ZIP 更新包资源")
    return max(candidates, key=_asset_score)


def _extract_sha256(text: str, asset_name: str = "") -> str:
    matches = re.findall(r"(?i)\bsha256\b[^a-f0-9]{0,20}([a-f0-9]{64})\b", text)
    if len(matches) == 1:
        return matches[0].lower()
    if asset_name:
        for line in text.splitlines():
            if asset_name in line:
                match = re.search(r"(?i)\b([a-f0-9]{64})\b", line)
                if match:
                    return match.group(1).lower()
    return ""


def github_release_to_manifest(release: dict[str, Any]) -> ManifestUpdateInfo:
    asset = select_github_release_asset(release)
    asset_name = str(asset.get("name") or "")
    download_url = str(asset.get("browser_download_url") or "")
    version = str(release.get("tag_name") or release.get("name") or "").strip()
    if not version:
        raise ValueError("GitHub Release 缺少版本 tag")
    if not download_url:
        raise ValueError(f"GitHub Release 资源 {asset_name or '<unknown>'} 缺少下载地址")

    digest = str(asset.get("digest") or "")
    sha256 = digest.split(":", 1)[1].strip().lower() if digest.lower().startswith("sha256:") else ""
    if not sha256:
        sha256 = _extract_sha256(str(release.get("body") or ""), asset_name)

    return ManifestUpdateInfo(
        version=version,
        url=download_url,
        sha256=sha256,
        size=asset.get("size"),
        notes=str(release.get("body") or ""),
        force=False,
        channel="stable",
        title=release.get("name") or version,
        source="github",
        asset_name=asset_name,
    )


class ManifestUpdateUtils:
    """Manifest based full-package updater.

    The manifest is intentionally small and host-agnostic so it can live on
    GitHub Releases, a static file server, or any CDN.
    """

    def __init__(
        self,
        *,
        current_version: str = __version__,
        app_root: str | Path | None = None,
        update_dir: str | Path | None = None,
    ):
        self.current_version = current_version
        self.app_root = Path(app_root or ROOT_PATH).resolve()
        self.update_dir = Path(update_dir or DEFAULT_UPDATE_DIR).resolve()
        self.data: ManifestUpdateInfo | None = None

    def get_latest_info(self, manifest_url: str, timeout: float = 10.0) -> ManifestUpdateInfo | None:
        manifest_url = manifest_url.strip()
        if not manifest_url:
            return None
        logger.info(f"获取更新清单 version={self.current_version} url={manifest_url}")
        payload = _read_json_from_url_or_file(manifest_url, timeout)
        self.data = ManifestUpdateInfo.model_validate(payload)
        return self.data

    def get_latest_github_info(
        self,
        repo: str = DEFAULT_GITHUB_REPO,
        timeout: float = 10.0,
    ) -> ManifestUpdateInfo | None:
        repo = repo.strip() or DEFAULT_GITHUB_REPO
        url = DEFAULT_GITHUB_RELEASE_API.format(repo=repo)
        logger.info(f"获取 GitHub Release version={self.current_version} repo={repo}")
        response = requests.get(url, headers=GITHUB_HEADERS, timeout=timeout)
        response.raise_for_status()
        self.data = github_release_to_manifest(response.json())
        return self.data

    def get_update_status(
        self,
        manifest_url: str | None = None,
        reload: bool = False,
        *,
        repo: str = DEFAULT_GITHUB_REPO,
    ) -> UpdateStatus:
        try:
            if not self.data or reload:
                self.data = (
                    self.get_latest_info(manifest_url)
                    if manifest_url
                    else self.get_latest_github_info(repo)
                )
            if not self.data:
                return UpdateStatus.FAILED
            if self.data.min_version and compare_versions(self.current_version, self.data.min_version) < 0:
                return UpdateStatus.UPDATE
            if is_development_version(self.current_version):
                return UpdateStatus.UPDATE
            if compare_versions(self.current_version, self.data.version) < 0:
                return UpdateStatus.UPDATE
            return UpdateStatus.LATEST
        except Exception as exc:
            logger.warning(f"检查更新失败: {exc}")
            return UpdateStatus.FAILED

    def package_path_for(self, manifest: ManifestUpdateInfo) -> Path:
        safe_version = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in manifest.version)
        return self.update_dir / f"NightChainsTech_{safe_version}.zip"

    def download_package(
        self,
        manifest: ManifestUpdateInfo,
        *,
        progress_changed: Callable[[int], None] | None = None,
        timeout: float = 30.0,
    ) -> Path:
        self.update_dir.mkdir(parents=True, exist_ok=True)
        package_path = self.package_path_for(manifest)
        parsed = urlparse(manifest.url)
        if parsed.scheme in ("", "file"):
            source = Path(parsed.path if parsed.scheme == "file" else manifest.url)
            package_path.write_bytes(source.read_bytes())
            if progress_changed:
                progress_changed(100)
            return package_path

        response = requests.get(manifest.url, stream=True, timeout=timeout)
        response.raise_for_status()
        total_size = int(response.headers.get("content-length") or manifest.size or 0)
        current_size = 0
        tmp_path = package_path.with_suffix(package_path.suffix + ".tmp")
        with tmp_path.open("wb") as file:
            for chunk in response.iter_content(1024 * 512):
                if not chunk:
                    continue
                file.write(chunk)
                current_size += len(chunk)
                if progress_changed and total_size > 0:
                    progress_changed(min(99, int(current_size / total_size * 100)))
        tmp_path.replace(package_path)
        if progress_changed:
            progress_changed(100)
        return package_path

    def verify_package(self, package_path: str | Path, manifest: ManifestUpdateInfo) -> None:
        if not manifest.sha256:
            logger.warning("更新包未提供 SHA256，跳过完整性校验")
            return
        actual = sha256_file(package_path)
        expected = manifest.sha256.lower()
        if actual.lower() != expected:
            raise ValueError(f"更新包 SHA256 校验失败: expected={expected} actual={actual}")

    def restart_args(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable]
        return [sys.executable, str((self.app_root / "gui.py").resolve())]

    def updater_executable(self) -> list[str]:
        script = self.app_root / "tools" / "apply_update.py"
        if not getattr(sys, "frozen", False):
            return [sys.executable, str(script.resolve())]

        candidates = (
            self.app_root / "NightChainsTechUpdater.exe",
            self.app_root / "updater.exe",
        )
        for path in candidates:
            if path.exists():
                return [str(path)]
        raise FileNotFoundError("未找到独立更新程序 NightChainsTechUpdater.exe")

    def build_updater_command(self, package_path: str | Path, manifest: ManifestUpdateInfo) -> list[str]:
        backup_dir = self.update_dir / "backup" / manifest.version
        command = self.updater_executable()
        command.extend(
            [
                "--package",
                str(Path(package_path).resolve()),
                "--target",
                str(self.app_root),
                "--backup-dir",
                str(backup_dir),
                "--wait-pid",
                str(os.getpid()),
                "--restart-args",
                json.dumps(self.restart_args(), ensure_ascii=False),
            ]
        )
        for path in DEFAULT_PRESERVE_PATHS:
            command.extend(["--preserve", path])
        return command

    def prepare_update(
        self,
        manifest: ManifestUpdateInfo,
        *,
        progress_changed: Callable[[int], None] | None = None,
    ) -> PreparedUpdate:
        package_path = self.download_package(manifest, progress_changed=progress_changed)
        self.verify_package(package_path, manifest)
        return PreparedUpdate(
            manifest=manifest,
            package_path=str(package_path),
            updater_command=self.build_updater_command(package_path, manifest),
            restart_args=self.restart_args(),
        )

    def launch_updater(self, prepared: PreparedUpdate) -> None:
        logger.info(f"启动独立更新程序: {prepared.updater_command}")
        subprocess.Popen(
            prepared.updater_command,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )
