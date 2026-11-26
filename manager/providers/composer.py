"""Composer Provider：使用当前 CLI 默认 PHP 运行。"""
from __future__ import annotations

from typing import Dict, List, Optional

from core import installer
from providers.base import Provider
from utils import shell


class ComposerProvider(Provider):
    name = "composer"

    def binary(self) -> str:
        prefix = installer.keg_prefix("composer")
        if prefix:
            return f"{prefix}/bin/composer"
        return "composer"

    def is_installed(self) -> bool:
        return installer.is_installed("composer")

    def install(self) -> None:
        if self.is_installed():
            print("Composer 已安装，跳过")
            return
        installer.install("composer")
        self.state.mark_installed("composer")
        print("Composer 安装完成")

    def _php_command(self) -> Optional[List[str]]:
        """优先使用 dev php switch 的默认版本执行 Composer。"""
        from providers.php import PHPProvider

        provider = PHPProvider()
        version = provider.current_cli()
        binary = provider.cli_binary(version) if version else None
        if not binary:
            return None
        return [str(binary), "-c", str(self.config.php_ini(version))]

    def _env(self, version: Optional[str] = None) -> Dict[str, str]:
        from providers.php import PHPProvider

        provider = PHPProvider()
        resolved = version or provider.current_cli()
        env = {
            "PATH": f"{self.config.home}/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        }
        if resolved:
            env["PHP_INI_SCAN_DIR"] = str(self.config.php_conf_d(resolved))
        return env

    def _run(self, extra: List[str]) -> "shell.CommandResult":
        php = self._php_command()
        composer = self.binary()
        if php:
            cmd = php + [composer] + extra
        else:
            cmd = [composer] + extra
        return shell.run(cmd, env=self._env(), quiet=True, timeout=600)

    def version(self) -> str:
        result = self._run(["--version", "--no-ansi"])
        return result.stdout.strip().splitlines()[0] if result.ok and result.stdout.strip() else "未安装"

    def diagnose(self) -> int:
        result = self._run(["diagnose", "--no-ansi"])
        print(result.stdout or result.stderr)
        return result.returncode

    def info(self) -> Dict[str, str]:
        from providers.php import PHPProvider

        return {
            "Composer": self.version(),
            "可执行文件": self.binary(),
            "使用 PHP": PHPProvider().current_cli() or "系统默认",
        }

    def uninstall(self) -> None:
        installer.uninstall("composer")
        self.state.mark_uninstalled("composer")
        print("Composer 已卸载")
