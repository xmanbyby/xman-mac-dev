"""系统信息、端口与进程检测。"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from utils import shell


@dataclass
class PortOwner:
    pid: int
    command: str
    port: int


def macos_version() -> str:
    return platform.mac_ver()[0] or "unknown"


def arch() -> str:
    return platform.machine()


def is_apple_silicon() -> bool:
    return arch() == "arm64"


def uid() -> int:
    return os.getuid()


def username() -> str:
    return os.environ.get("USER") or Path.home().name


def group_name() -> str:
    import grp

    try:
        return grp.getgrgid(os.getgid()).gr_name
    except (KeyError, OSError):
        return "staff"


def brew_prefix() -> str:
    return shell.output(["brew", "--prefix"])


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def kill_pid(pid: int, sig: str = "TERM") -> bool:
    """只终止管理器自己启动并记录的进程。"""
    import signal

    sig_map = {"TERM": signal.SIGTERM, "KILL": signal.SIGKILL, "QUIT": signal.SIGQUIT,
               "HUP": signal.SIGHUP}
    try:
        os.kill(pid, sig_map.get(sig, signal.SIGTERM))
        return True
    except OSError:
        return False


def read_pid(pid_file: Path) -> Optional[int]:
    try:
        text = pid_file.read_text(encoding="utf-8").strip()
        return int(text.split()[0])
    except (OSError, ValueError, IndexError):
        return None


def remove_pid(pid_file: Path) -> None:
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass


def port_owners(port: int) -> List[PortOwner]:
    owners: List[PortOwner] = []
    result = shell.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpc"], quiet=True, timeout=15)
    pid = 0
    command = ""
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            pid = int(line[1:] or 0)
        elif line.startswith("c"):
            command = line[1:]
            if pid:
                owners.append(PortOwner(pid=pid, command=command, port=port))
            pid, command = 0, ""
    return owners


def port_in_use(port: int) -> bool:
    return bool(port_owners(port))


def port_connectable(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def socket_connectable(path: Path, timeout: float = 1.0) -> bool:
    if not path.exists():
        return False
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(str(path))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def disk_free_gb(path: Path) -> float:
    target = path if path.exists() else path.parent
    try:
        usage = shutil.disk_usage(str(target))
        return round(usage.free / (1024 ** 3), 1)
    except OSError:
        return 0.0


def total_memory_gb() -> float:
    try:
        out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
        return round(int(out) / (1024 ** 3), 1)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def find_binary(name: str, extra_paths: Optional[List[str]] = None) -> Optional[str]:
    """在 PATH 与 Homebrew 常见目录中查找二进制。"""
    found = shutil.which(name)
    if found:
        return found
    candidates = [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/usr/sbin",
    ]
    for directory in candidates + list(extra_paths or []):
        candidate = Path(directory) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def brew_services_running(name: str) -> bool:
    result = shell.run(["brew", "services", "list"], quiet=True, timeout=60)
    if not result.ok:
        return False
    for line in result.stdout.splitlines():
        parts = line.split()
        if parts and parts[0] == name and len(parts) > 1 and parts[1] == "started":
            return True
    return False
