"""launchd 服务生命周期管理。统一由 dev 管理，不使用 brew services。"""
from __future__ import annotations

import plistlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.config import get_config
from utils import shell, system
from utils.log import get_logger

LABEL_PREFIX = "com.devenv"


class ServiceError(RuntimeError):
    pass


@dataclass
class ServiceSpec:
    name: str
    label: str
    args: List[str]
    log_path: Path
    pid_file: Optional[Path] = None
    port: Optional[int] = None
    socket: Optional[Path] = None
    workdir: Optional[Path] = None
    env: Dict[str, str] = field(default_factory=dict)
    health: Optional[Callable[[], bool]] = None
    display: str = ""

    @property
    def title(self) -> str:
        return self.display or self.name


def _gui_domain() -> str:
    return f"gui/{system.uid()}"


class Launchd:
    def __init__(self) -> None:
        self.config = get_config()
        self.dir = self.config.launch_agents_dir
        self.log = get_logger()

    def plist_path(self, label: str) -> Path:
        return self.dir / f"{label}.plist"

    def write(self, spec: ServiceSpec) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        spec.log_path.parent.mkdir(parents=True, exist_ok=True)
        if spec.pid_file:
            spec.pid_file.parent.mkdir(parents=True, exist_ok=True)
        if spec.workdir:
            spec.workdir.mkdir(parents=True, exist_ok=True)
        env = {
            "PATH": "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
            "DEV_HOME": str(self.config.home),
        }
        env.update(spec.env)
        payload = {
            "Label": spec.label,
            "ProgramArguments": [str(item) for item in spec.args],
            "RunAtLoad": False,
            "KeepAlive": False,
            "ProcessType": "Background",
            "ThrottleInterval": 5,
            "StandardOutPath": str(spec.log_path),
            "StandardErrorPath": str(spec.log_path),
            "EnvironmentVariables": env,
        }
        if spec.workdir:
            payload["WorkingDirectory"] = str(spec.workdir)
        path = self.plist_path(spec.label)
        with open(path, "wb") as fh:
            plistlib.dump(payload, fh)
        self.log.info(f"plist written: {path}")
        return path

    def remove(self, label: str) -> None:
        path = self.plist_path(label)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    def is_loaded(self, label: str) -> bool:
        return shell.run(["launchctl", "print", f"{_gui_domain()}/{label}"], quiet=True, timeout=20).ok

    def bootstrap(self, spec: ServiceSpec) -> None:
        path = self.write(spec)
        if self.is_loaded(spec.label):
            shell.run(["launchctl", "bootout", f"{_gui_domain()}/{spec.label}"], quiet=True, timeout=30)
            time.sleep(0.3)
        result = shell.run(["launchctl", "bootstrap", _gui_domain(), str(path)], quiet=True, timeout=60)
        if not result.ok and "already bootstrapped" not in result.brief():
            raise ServiceError(f"launchctl bootstrap 失败: {result.brief()}")

    def bootout(self, label: str) -> None:
        if self.is_loaded(label):
            shell.run(["launchctl", "bootout", f"{_gui_domain()}/{label}"], quiet=True, timeout=60)

    def kickstart(self, label: str) -> None:
        result = shell.run(
            ["launchctl", "kickstart", "-k", f"{_gui_domain()}/{label}"], quiet=True, timeout=60
        )
        if not result.ok:
            raise ServiceError(f"launchctl kickstart 失败: {result.brief()}")


class ServiceManager:
    def __init__(self) -> None:
        self.launchd = Launchd()
        self.config = get_config()
        self.log = get_logger()

    # ---------------------------------------------------------------- 状态判断
    def is_running(self, spec: ServiceSpec) -> bool:
        if spec.health:
            try:
                return bool(spec.health())
            except Exception:  # noqa: BLE001 - 健康检查失败即视为未运行
                return False
        if spec.port:
            return system.port_connectable(spec.port)
        if spec.socket:
            return system.socket_connectable(spec.socket)
        if spec.pid_file:
            pid = system.read_pid(spec.pid_file)
            return bool(pid and system.pid_alive(pid))
        return self.launchd.is_loaded(spec.label)

    def pid(self, spec: ServiceSpec) -> Optional[int]:
        if spec.pid_file:
            pid = system.read_pid(spec.pid_file)
            if pid and system.pid_alive(pid):
                return pid
        if spec.port:
            owners = system.port_owners(spec.port)
            if owners:
                return owners[0].pid
        return None

    # ---------------------------------------------------------------- 生命周期
    def start(self, spec: ServiceSpec, timeout: int = 30) -> bool:
        if self.is_running(spec):
            self.log.info(f"{spec.name} already running")
            return True
        if spec.port and system.port_in_use(spec.port):
            owners = system.port_owners(spec.port)
            detail = ", ".join(f"PID {item.pid} ({item.command})" for item in owners)
            raise ServiceError(f"端口 {spec.port} 已被占用: {detail}")
        self.launchd.bootstrap(spec)
        self.launchd.kickstart(spec.label)
        if not self.wait_until(spec, True, timeout):
            tail = self._log_tail(spec.log_path)
            self.launchd.bootout(spec.label)
            raise ServiceError(f"{spec.title} 启动失败或超时。{tail}")
        self.log.info(f"{spec.name} started")
        return True

    def stop(self, spec: ServiceSpec, timeout: int = 30) -> bool:
        if not self.is_running(spec) and not self.launchd.is_loaded(spec.label):
            self.log.info(f"{spec.name} already stopped")
            return True
        self.launchd.bootout(spec.label)
        self.wait_until(spec, False, timeout)
        if self.is_running(spec):
            pid = self.pid(spec)
            if pid:
                system.kill_pid(pid, "TERM")
                self.wait_until(spec, False, timeout)
        if spec.pid_file:
            system.remove_pid(spec.pid_file)
        self.log.info(f"{spec.name} stopped")
        return True

    def restart(self, spec: ServiceSpec, timeout: int = 30) -> bool:
        self.stop(spec, timeout)
        return self.start(spec, timeout)

    def wait_until(self, spec: ServiceSpec, running: bool, timeout: int) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_running(spec) == running:
                return True
            time.sleep(0.4)
        return self.is_running(spec) == running

    def _log_tail(self, path: Path, lines: int = 8) -> str:
        try:
            content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return ""
        if not content:
            return ""
        return "最近日志: " + " | ".join(content[-lines:])

    def remove(self, spec: ServiceSpec) -> None:
        self.launchd.bootout(spec.label)
        self.launchd.remove(spec.label)
