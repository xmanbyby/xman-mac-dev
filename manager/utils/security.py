"""macOS Keychain 凭据管理。密码不写入普通配置文件与日志。"""
from __future__ import annotations

import getpass
from typing import Optional

from utils import shell
from utils.log import get_logger

SERVICE_PREFIX = "dev."
ACCOUNT = getpass.getuser()


def keychain_set(name: str, password: str) -> bool:
    service = name if name.startswith(SERVICE_PREFIX) else SERVICE_PREFIX + name
    result = shell.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-a",
            ACCOUNT,
            "-s",
            service,
            "-w",
            password,
        ],
        quiet=True,
        timeout=60,
    )
    if not result.ok:
        get_logger().error(f"keychain set failed: {service} ({result.brief()})")
        return False
    get_logger().info(f"keychain updated: {service}")
    return True


def keychain_get(name: str) -> Optional[str]:
    service = name if name.startswith(SERVICE_PREFIX) else SERVICE_PREFIX + name
    result = shell.run(
        ["security", "find-generic-password", "-a", ACCOUNT, "-s", service, "-w"],
        quiet=True,
        timeout=30,
    )
    if result.ok:
        return result.stdout.strip()
    return None


def keychain_delete(name: str) -> bool:
    service = name if name.startswith(SERVICE_PREFIX) else SERVICE_PREFIX + name
    result = shell.run(
        ["security", "delete-generic-password", "-a", ACCOUNT, "-s", service],
        quiet=True,
        timeout=30,
    )
    return result.ok


def keychain_exists(name: str) -> bool:
    return keychain_get(name) is not None
