"""文件系统工具与统一目录布局。"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Iterable


PHP_VERSIONS = ["8.1", "8.2", "8.3", "8.4", "8.5"]
MYSQL_VERSIONS = ["8.0", "8.4"]


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    tmp.replace(path)


def write_text(path: Path, content: str, mode: int = 0o644) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.chmod(tmp, mode)
    tmp.replace(path)


def read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return default


def backup_file(path: Path, backup_dir: Path) -> Path | None:
    """修改重要文件前保留一份副本，返回副本路径。"""
    if not path.exists():
        return None
    import datetime

    ensure_dir(backup_dir)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, target)
    return target


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def ensure_layout(root: Path) -> None:
    """创建方案中约定的完整目录结构（幂等）。"""
    dirs: Iterable[Path] = [
        root / "bin",
        root / "config" / "nginx" / "projects",
        root / "config" / "mysql" / "8.0",
        root / "config" / "mysql" / "8.4",
        root / "config" / "redis",
        root / "config" / "projects",
        root / "data" / "mysql" / "8.0" / "data",
        root / "data" / "mysql" / "8.4" / "data",
        root / "data" / "mysql" / "backups",
        root / "data" / "mysql" / "8.0" / "files",
        root / "data" / "mysql" / "8.4" / "files",
        root / "data" / "redis" / "data",
        root / "data" / "redis" / "backups",
        root / "logs" / "nginx",
        root / "logs" / "mysql",
        root / "logs" / "redis",
        root / "logs" / "manager",
        root / "run" / "nginx",
        root / "run" / "mysql",
        root / "run" / "redis",
        root / "run" / "php",
        root / "state",
        root / "backups" / "config",
        root / "backups" / "mysql",
        root / "backups" / "redis",
        root / "backups" / "system",
        root / "software" / "redis" / "versions",
    ]
    for version in PHP_VERSIONS:
        dirs.append(root / "software" / "php" / version)
        dirs.append(root / "config" / "php" / version / "conf.d")
        dirs.append(root / "logs" / "php" / version)
    for version in MYSQL_VERSIONS:
        dirs.append(root / "software" / "mysql" / version)
    for path in dirs:
        ensure_dir(path)
