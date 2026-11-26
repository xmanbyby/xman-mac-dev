"""PHP 命令。"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer

from commands import ui
from core.config import get_config
from providers.php import PHPProvider
from utils.filesystem import PHP_VERSIONS

app = typer.Typer(help="PHP 多版本管理", no_args_is_help=True)
fpm_app = typer.Typer(help="PHP-FPM 管理", no_args_is_help=True)
app.add_typer(fpm_app, name="fpm")


@app.command("install")
def install_cmd(version: str = typer.Argument(..., help="8.1 / 8.2 / 8.3 / 8.4 / 8.5")) -> None:
    """安装指定 PHP 版本。"""
    if version not in PHP_VERSIONS:
        ui.error(f"不支持的版本: {version}，可选: {', '.join(PHP_VERSIONS)}")
        raise typer.Exit(code=1)
    PHPProvider().install(version)


@app.command("uninstall")
def uninstall_cmd(version: str) -> None:
    """卸载指定 PHP 版本（保留配置与日志）。"""
    PHPProvider().uninstall(version)


@app.command("list")
def list_cmd() -> None:
    """列出 PHP 版本。"""
    provider = PHPProvider()
    current = provider.current_cli()
    rows = []
    for version in PHP_VERSIONS:
        installed = provider.is_installed(version)
        rows.append([
            version,
            "已安装" if installed else "-",
            "是" if version == current else "",
            "running" if installed and provider.fpm_running(version) else "stopped",
            provider.version_string(version) if installed else "-",
        ])
    ui.table("PHP 版本", ["版本", "安装", "CLI 默认", "FPM", "实际版本"], rows)


@app.command("switch")
def switch_cmd(version: str) -> None:
    """切换 CLI 默认版本（不影响运行中的 FPM）。"""
    PHPProvider().switch_cli(version)


@app.command("current")
def current_cmd() -> None:
    """显示当前 CLI 默认版本。"""
    provider = PHPProvider()
    version = provider.current_cli()
    if not version:
        ui.warn("未安装任何 PHP 版本")
        raise typer.Exit(code=1)
    typer.echo(version)


@app.command("info")
def info_cmd(version: Optional[str] = typer.Argument(None)) -> None:
    """查看版本信息。"""
    provider = PHPProvider()
    version = version or provider.current_cli()
    if not version:
        ui.error("未安装任何 PHP 版本")
        raise typer.Exit(code=1)
    ui.kv(f"PHP {version}", provider.info(version))


@app.command("ini")
def ini_cmd(version: Optional[str] = typer.Argument(None)) -> None:
    """显示 php.ini 路径与关键配置。"""
    provider = PHPProvider()
    version = version or provider.current_cli()
    if not version:
        ui.error("未安装任何 PHP 版本")
        raise typer.Exit(code=1)
    path = get_config().php_ini(version)
    typer.echo(str(path))
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(";") and "=" in stripped:
                typer.echo(f"  {stripped}")


@app.command("run", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
def run_cmd(
    ctx: typer.Context,
    version: str = typer.Argument(..., help="PHP 版本"),
    args: Optional[List[str]] = typer.Argument(None, help="传递给 PHP 的参数"),
) -> None:
    """用指定版本执行 PHP 命令，例如: dev php run 8.3 composer install"""
    full_args = list(args or []) + list(ctx.args or [])
    code = PHPProvider().run(version, full_args)
    if code != 0:
        raise typer.Exit(code=code)


# ---------------------------------------------------------------------- fpm
@fpm_app.command("start")
def fpm_start(version: Optional[str] = typer.Argument(None)) -> None:
    """启动 PHP-FPM（不指定版本则启动所有已启用版本）。"""
    provider = PHPProvider()
    versions = [version] if version else provider.enabled_fpm_versions()
    if not versions:
        ui.warn("没有已启用的 PHP 版本，可执行: dev enable php --version 8.3")
        raise typer.Exit(code=1)
    failed = False
    for item in versions:
        try:
            provider.start_fpm(item)
        except Exception as exc:  # noqa: BLE001
            failed = True
            ui.error(str(exc))
    if failed:
        raise typer.Exit(code=1)


@fpm_app.command("stop")
def fpm_stop(version: Optional[str] = typer.Argument(None)) -> None:
    """停止 PHP-FPM。"""
    provider = PHPProvider()
    versions = [version] if version else provider.installed_versions()
    for item in versions:
        provider.stop_fpm(item)


@fpm_app.command("restart")
def fpm_restart(version: Optional[str] = typer.Argument(None)) -> None:
    """重启 PHP-FPM。"""
    provider = PHPProvider()
    versions = [version] if version else provider.enabled_fpm_versions()
    for item in versions:
        provider.restart_fpm(item)


@fpm_app.command("status")
def fpm_status() -> None:
    """查看 PHP-FPM 状态。"""
    provider = PHPProvider()
    rows = [
        [version, "running" if provider.fpm_running(version) else "stopped",
         str(get_config().php_socket(version))]
        for version in provider.installed_versions()
    ]
    if not rows:
        ui.warn("未安装任何 PHP 版本")
        return
    ui.table("PHP-FPM 状态", ["版本", "状态", "Socket"], rows)
