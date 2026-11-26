"""PHP 扩展命令。"""
from __future__ import annotations

from typing import Optional

import typer

from commands import ui
from core import installer
from providers.php import DEFAULT_DISABLED, PECL_EXTENSIONS, PHPProvider

app = typer.Typer(help="PHP 扩展管理", no_args_is_help=True)


def _version(version: Optional[str]) -> str:
    provider = PHPProvider()
    resolved = version or provider.current_cli()
    if not resolved:
        ui.error("未安装任何 PHP 版本")
        raise typer.Exit(code=1)
    if not provider.is_installed(resolved):
        ui.error(f"PHP {resolved} 未安装")
        raise typer.Exit(code=1)
    return resolved


@app.command("search")
def search_cmd(term: str) -> None:
    """搜索可管理的扩展。"""
    matches = [name for name in PECL_EXTENSIONS if term.lower() in name.lower()]
    if not matches:
        ui.warn(f"未找到扩展: {term}（当前管理: {', '.join(PECL_EXTENSIONS)}）")
        return
    rows = []
    for name in matches:
        rows.append([name, "PECL / shivammathur/extensions", "编译安装"])
    ui.table("扩展搜索结果", ["扩展", "来源", "方式"], rows)


@app.command("install")
def install_cmd(
    extension: str = typer.Argument(...),
    php_version: Optional[str] = typer.Option(None, "--php", help="PHP 版本"),
) -> None:
    """安装并启用扩展。"""
    version = _version(php_version)
    PHPProvider().ext_install(version, extension)


@app.command("enable")
def enable_cmd(
    extension: str = typer.Argument(...),
    php_version: Optional[str] = typer.Option(None, "--php"),
) -> None:
    """启用扩展。"""
    PHPProvider().ext_enable(_version(php_version), extension)


@app.command("disable")
def disable_cmd(
    extension: str = typer.Argument(...),
    php_version: Optional[str] = typer.Option(None, "--php"),
) -> None:
    """停用扩展。"""
    PHPProvider().ext_disable(_version(php_version), extension)


@app.command("uninstall")
def uninstall_cmd(
    extension: str = typer.Argument(...),
    php_version: Optional[str] = typer.Option(None, "--php"),
) -> None:
    """卸载扩展。"""
    PHPProvider().ext_uninstall(_version(php_version), extension)


@app.command("list")
def list_cmd(php_version: Optional[str] = typer.Option(None, "--php")) -> None:
    """列出当前加载的扩展。"""
    version = _version(php_version)
    provider = PHPProvider()
    modules = provider.module_list(version)
    if not modules:
        ui.warn("未读取到扩展列表")
        return
    rows = []
    for name in modules:
        lowered = name.lower()
        enabled_file = provider.ext_enabled(version, lowered)
        rows.append([name, "conf.d" if enabled_file else "内置"])
    ui.table(f"PHP {version} 扩展 ({len(modules)})", ["扩展", "来源"], rows)


@app.command("doctor")
def doctor_cmd(php_version: Optional[str] = typer.Option(None, "--php")) -> None:
    """检查默认扩展集合的安装情况。"""
    version = _version(php_version)
    provider = PHPProvider()
    modules = {name.lower() for name in provider.module_list(version)}
    conf_d = provider.config.php_conf_d(version)
    rows = []
    for name in PECL_EXTENSIONS:
        disabled = (conf_d / f"{name}.ini.disabled").exists()
        if name in modules and provider.ext_enabled(version, name):
            state = "已启用"
        elif disabled:
            state = "已安装（已停用）"
        elif name in modules:
            state = "已加载（未通过 conf.d 启用）"
        else:
            state = "未安装"
        expected = "默认关闭" if name in DEFAULT_DISABLED else "默认启用"
        rows.append([name, state, expected])
    ui.table(f"PHP {version} 扩展检查", ["扩展", "状态", "策略"], rows)
    missing = [row[0] for row in rows if row[1] == "未安装"]
    if missing:
        ui.warn("缺失扩展可用 dev ext install <name> --php=" + version + " 安装")
