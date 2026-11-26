"""Node.js 命令。"""
from __future__ import annotations

from typing import Optional

import typer

from commands import ui
from providers.node import NodeProvider

app = typer.Typer(help="Node.js / fnm 管理", no_args_is_help=True)


@app.command("install")
def install_cmd(version: Optional[str] = typer.Argument(None, help="如 22 / 24，默认读取 .env")) -> None:
    """安装 fnm 与指定 Node 版本。"""
    from core import installer

    provider = NodeProvider()
    if not provider.is_installed():
        installer.install("fnm")
    target = version or provider.config.get("NODE_DEFAULT_VERSION", "22")
    provider.install_version(target)
    provider.use_default(target)
    provider.state.mark_installed("node")


@app.command("list")
def list_cmd() -> None:
    """列出已安装 Node 版本。"""
    provider = NodeProvider()
    ui.kv("Node.js", provider.info())


@app.command("default")
def default_cmd(version: str) -> None:
    """设置默认 Node 版本。"""
    NodeProvider().use_default(version)


@app.command("current")
def current_cmd() -> None:
    typer.echo(NodeProvider().current())


@app.command("doctor")
def doctor_cmd() -> None:
    from core.doctor import Doctor

    ui.checks_table(Doctor().run("node"))
