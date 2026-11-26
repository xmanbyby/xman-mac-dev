"""Homebrew 安装器：只负责软件包，不管理服务生命周期。"""
from __future__ import annotations

from typing import Dict, List, Optional

from utils import shell, system
from utils.log import get_logger


class InstallError(RuntimeError):
    pass


def brew_available() -> bool:
    return system.find_binary("brew") is not None


def brew_prefix() -> str:
    return system.brew_prefix() or "/opt/homebrew"


def brew_env() -> Dict[str, str]:
    prefix = brew_prefix()
    return {
        "HOMEBREW_NO_AUTO_UPDATE": "1",
        "HOMEBREW_NO_INSTALL_CLEANUP": "1",
        "PATH": f"{prefix}/bin:{prefix}/sbin:/usr/bin:/bin:/usr/sbin:/sbin",
    }


def installed_versions(formula: str) -> List[str]:
    result = shell.run(["brew", "list", "--versions", formula], quiet=True, timeout=120)
    if not result.ok or not result.stdout.strip():
        return []
    parts = result.stdout.strip().split()
    return parts[1:]


def is_installed(formula: str) -> bool:
    return bool(installed_versions(formula))


def formula_exists(formula: str) -> bool:
    result = shell.run(["brew", "info", "--json=v2", formula], quiet=True, timeout=180)
    return result.ok and result.stdout.strip().startswith("{")


def tap(name: str) -> None:
    if not name:
        return
    result = shell.run(["brew", "tap", name], quiet=True, timeout=300, env=brew_env())
    if not result.ok and "already tapped" not in result.brief().lower():
        raise InstallError(f"添加 Homebrew tap 失败: {name} ({result.brief()})")


def install(formula: str, tap_name: Optional[str] = None, force: bool = False) -> None:
    log = get_logger()
    if is_installed(formula) and not force:
        log.info(f"{formula} 已安装，跳过")
        return
    if tap_name:
        tap(tap_name)
    if not formula_exists(formula):
        hint = f" 可尝试: brew trust {tap_name}" if tap_name else ""
        raise InstallError(f"Homebrew 中不存在公式或 tap 未信任: {formula}。{hint}")
    print(f"安装 {formula} ...")
    result = shell.run_stream(["brew", "install", formula], timeout=3600, env=brew_env())
    if not result.ok:
        raise InstallError(f"安装 {formula} 失败: {result.brief()[-1500:]}")


def upgrade(formula: str) -> None:
    result = shell.run_stream(["brew", "upgrade", formula], timeout=3600, env=brew_env())
    if not result.ok:
        raise InstallError(f"升级 {formula} 失败: {result.brief()[-1500:]}")


def uninstall(formula: str) -> bool:
    if not is_installed(formula):
        return True
    result = shell.run_stream(["brew", "uninstall", formula], timeout=1800, env=brew_env())
    if not result.ok and "No such keg" not in result.brief():
        raise InstallError(f"卸载 {formula} 失败: {result.brief()[-1500:]}")
    return True


def keg_prefix(formula: str) -> Optional[str]:
    result = shell.run(["brew", "--prefix", formula], quiet=True, timeout=60)
    if result.ok and result.stdout.strip():
        return result.stdout.strip()
    return None


def services_list() -> List[str]:
    """列出被 brew services 托管的服务，用于检测双重托管。"""
    result = shell.run(["brew", "services", "list"], quiet=True, timeout=60)
    names: List[str] = []
    if not result.ok:
        return names
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "started":
            names.append(parts[0])
    return names
