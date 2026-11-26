"""状态文件管理（仅作记录，真实状态必须通过进程/端口/Socket 检查）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import get_config
from utils.filesystem import read_json, write_json

INSTALLED = "installed.json"
SERVICES = "services.json"
VERSIONS = "versions.json"
MIGRATIONS = "migrations.json"

DEFAULT_INSTALLED: Dict[str, Any] = {
    "php": [],
    "nginx": False,
    "mysql": [],
    "redis": False,
    "node": False,
    "composer": False,
}

DEFAULT_SERVICES: Dict[str, Any] = {}
DEFAULT_VERSIONS: Dict[str, Any] = {"php_cli": "", "mysql": "", "node": ""}


class State:
    def __init__(self, state_dir: Optional[Path] = None) -> None:
        self.dir = state_dir or get_config().state_dir
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.dir / name

    def read(self, name: str, default: Any) -> Any:
        data = read_json(self._path(name), None)
        return data if data is not None else default

    def write(self, name: str, data: Any) -> None:
        write_json(self._path(name), data)

    # ---------------------------------------------------------------- 快捷方法
    def installed(self) -> Dict[str, Any]:
        data = self.read(INSTALLED, dict(DEFAULT_INSTALLED))
        for key, value in DEFAULT_INSTALLED.items():
            data.setdefault(key, value.copy() if isinstance(value, list) else value)
        return data

    def save_installed(self, data: Dict[str, Any]) -> None:
        self.write(INSTALLED, data)

    def mark_installed(self, component: str, version: Optional[str] = None) -> None:
        data = self.installed()
        if version:
            versions: List[str] = list(data.get(component) or [])
            if version not in versions:
                versions.append(version)
                versions.sort()
            data[component] = versions
        else:
            data[component] = True
        self.save_installed(data)

    def mark_uninstalled(self, component: str, version: Optional[str] = None) -> None:
        data = self.installed()
        if version:
            versions = [item for item in (data.get(component) or []) if item != version]
            data[component] = versions
        else:
            data[component] = [] if isinstance(data.get(component), list) else False
        self.save_installed(data)

    def services(self) -> Dict[str, Any]:
        return self.read(SERVICES, dict(DEFAULT_SERVICES))

    def save_services(self, data: Dict[str, Any]) -> None:
        self.write(SERVICES, data)

    def versions(self) -> Dict[str, Any]:
        data = self.read(VERSIONS, dict(DEFAULT_VERSIONS))
        for key, value in DEFAULT_VERSIONS.items():
            data.setdefault(key, value)
        return data

    def save_versions(self, data: Dict[str, Any]) -> None:
        self.write(VERSIONS, data)

    def set_version(self, key: str, value: str) -> None:
        data = self.versions()
        data[key] = value
        self.save_versions(data)

    def migrations(self) -> Dict[str, Any]:
        return self.read(MIGRATIONS, {})

    def init_files(self) -> None:
        if not self._path(INSTALLED).exists():
            self.write(INSTALLED, DEFAULT_INSTALLED)
        if not self._path(SERVICES).exists():
            self.write(SERVICES, DEFAULT_SERVICES)
        if not self._path(VERSIONS).exists():
            self.write(VERSIONS, DEFAULT_VERSIONS)
        if not self._path(MIGRATIONS).exists():
            self.write(MIGRATIONS, {})


_state: Optional[State] = None


def get_state() -> State:
    global _state
    if _state is None:
        _state = State()
    return _state
