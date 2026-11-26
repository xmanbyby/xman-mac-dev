"""Node.js Provider：通过 fnm 管理多版本。"""
from __future__ import annotations

from typing import Dict, List, Optional

from core import installer
from providers.base import Provider
from utils import shell, system


class NodeProvider(Provider):
    name = "node"

    def fnm(self) -> Optional[str]:
        prefix = installer.keg_prefix("fnm")
        if prefix:
            candidate = f"{prefix}/bin/fnm"
            if system.find_binary("fnm", [f"{prefix}/bin"]):
                return candidate
        return system.find_binary("fnm")

    def is_installed(self) -> bool:
        return self.fnm() is not None

    def install(self) -> None:
        if not self.is_installed():
            installer.install("fnm")
        version = self.config.get("NODE_DEFAULT_VERSION", "22")
        self.install_version(version)
        self.use_default(version)
        self.state.mark_installed("node")
        print(f"Node.js 环境就绪（fnm + Node {version}）")

    def install_version(self, version: str) -> None:
        fnm = self.fnm()
        if not fnm:
            raise RuntimeError("fnm 未安装")
        result = shell.run([fnm, "install", version], quiet=True, timeout=900)
        if not result.ok:
            raise RuntimeError(f"Node {version} 安装失败: {result.brief()}")
        print(f"Node {version} 已安装")

    def use_default(self, version: str) -> None:
        fnm = self.fnm()
        if not fnm:
            raise RuntimeError("fnm 未安装")
        result = shell.run([fnm, "default", version], quiet=True, timeout=120)
        if not result.ok:
            raise RuntimeError(f"设置 Node 默认版本失败: {result.brief()}")
        self.config.set_env("NODE_DEFAULT_VERSION", version)
        self.state.set_version("node", version)
        print(f"Node 默认版本已设置为 {version}")

    def list_versions(self) -> List[str]:
        fnm = self.fnm()
        if not fnm:
            return []
        result = shell.run([fnm, "list"], quiet=True, timeout=60)
        versions: List[str] = []
        for line in result.stdout.splitlines():
            line = line.strip().lstrip("*").strip()
            if not line:
                continue
            parts = line.split()
            if parts and parts[0].lower().startswith("v"):
                versions.append(parts[0])
        return versions

    def current(self) -> str:
        stored = self.state.versions().get("node")
        if stored:
            return stored
        fnm = self.fnm()
        if fnm:
            result = shell.run([fnm, "list"], quiet=True, timeout=60)
            for line in result.stdout.splitlines():
                if "default" in line:
                    parts = line.replace("*", " ").split()
                    for part in parts:
                        if part.lower().startswith("v"):
                            return part
        return "-"

    def info(self) -> Dict[str, str]:
        return {
            "fnm": self.fnm() or "未安装",
            "已安装版本": ", ".join(self.list_versions()) or "-",
            "默认版本": self.current(),
            "系统 node": shell.output(["node", "-v"]) or "-",
        }

    def uninstall(self) -> None:
        installer.uninstall("fnm")
        self.state.mark_uninstalled("node")
        print("fnm 已卸载（Node 版本目录保留）")
