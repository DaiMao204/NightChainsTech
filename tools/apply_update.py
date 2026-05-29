from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path


def wait_for_process(pid: int, timeout: float = 90.0) -> None:
    if pid <= 0:
        return
    try:
        import psutil

        process = psutil.Process(pid)
        process.wait(timeout=timeout)
        return
    except Exception:
        pass

    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        try:
            import os

            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.5)


def extract_update(package_path: Path, work_dir: Path) -> Path:
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "r") as archive:
        archive.extractall(work_dir)

    entries = [entry for entry in work_dir.iterdir() if entry.name != "__MACOSX"]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return work_dir


def remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def replace_from_staging(source_root: Path, target_root: Path, backup_dir: Path, preserve: set[str]) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    moved: list[tuple[Path, Path, Path]] = []
    try:
        for source in source_root.iterdir():
            if source.name in preserve:
                continue
            target = target_root / source.name
            backup = backup_dir / source.name
            if backup.exists():
                remove_path(backup)
            if target.exists() or target.is_symlink():
                shutil.move(str(target), str(backup))
            shutil.move(str(source), str(target))
            moved.append((source, target, backup))
    except Exception:
        for _, target, backup in reversed(moved):
            try:
                if target.exists() or target.is_symlink():
                    remove_path(target)
                if backup.exists() or backup.is_symlink():
                    shutil.move(str(backup), str(target))
            except Exception:
                pass
        raise


def write_result(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply an Auto Resonance ZIP update after the main app exits.")
    parser.add_argument("--package", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--wait-pid", type=int, default=0)
    parser.add_argument("--preserve", action="append", default=[])
    parser.add_argument("--restart-args", default="")
    args = parser.parse_args()

    package_path = Path(args.package).resolve()
    target_root = Path(args.target).resolve()
    backup_dir = Path(args.backup_dir).resolve()
    work_dir = backup_dir.parent / "staging" / backup_dir.name
    result_path = backup_dir.parent / "last_update_result.json"

    try:
        wait_for_process(args.wait_pid)
        source_root = extract_update(package_path, work_dir)
        preserve = set(args.preserve or [])
        replace_from_staging(source_root, target_root, backup_dir, preserve)
        write_result(
            result_path,
            {
                "ok": True,
                "package": str(package_path),
                "target": str(target_root),
                "backup": str(backup_dir),
                "preserve": sorted(preserve),
            },
        )
        if args.restart_args:
            restart_args = json.loads(args.restart_args)
            if restart_args:
                subprocess.Popen(restart_args, cwd=str(target_root))
        return 0
    except Exception as exc:
        write_result(
            result_path,
            {
                "ok": False,
                "package": str(package_path),
                "target": str(target_root),
                "backup": str(backup_dir),
                "error": str(exc),
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
