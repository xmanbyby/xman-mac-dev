#!/usr/bin/env python3
"""DevEnvironment 统一命令行入口。"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
sys.path.insert(0, str(BASE))
os.environ.setdefault("DEV_HOME", str(ROOT))

import click  # noqa: E402
import typer  # noqa: E402

from commands import composer as composer_cmd  # noqa: E402
from commands import config_cmd  # noqa: E402
from commands import ext as ext_cmd  # noqa: E402
from commands import global_cmd  # noqa: E402
from commands import mysql as mysql_cmd  # noqa: E402
from commands import nginx as nginx_cmd  # noqa: E402
from commands import node as node_cmd  # noqa: E402
from commands import php as php_cmd  # noqa: E402
from commands import project as project_cmd  # noqa: E402
from commands import redis as redis_cmd  # noqa: E402
from core.backup import BackupError  # noqa: E402
from core.database import DatabaseError  # noqa: E402
from core.installer import InstallError  # noqa: E402
from core.project import ProjectError  # noqa: E402
from core.service import ServiceError  # noqa: E402
from commands import ui  # noqa: E402

app = typer.Typer(
    help="macOS 原生本地开发环境管理器（PHP / Nginx / MySQL / Redis / Node / Composer）",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)

app.add_typer(global_cmd.app)
app.add_typer(config_cmd.app, name="config")
app.add_typer(php_cmd.app, name="php")
app.add_typer(ext_cmd.app, name="ext")
app.add_typer(nginx_cmd.app, name="nginx")
app.add_typer(mysql_cmd.app, name="mysql")
app.add_typer(redis_cmd.app, name="redis")
app.add_typer(node_cmd.app, name="node")
app.add_typer(composer_cmd.app, name="composer")
app.add_typer(project_cmd.app, name="project")


@app.command("help")
def help_cmd(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="命令，如 php / mysql / project"),
    subcommand: Optional[str] = typer.Argument(None, help="二级命令，如 fpm / user"),
) -> None:
    """显示命令帮助，例如: dev help / dev help php / dev help php fpm"""
    root_ctx = ctx.find_root()
    if not name:
        typer.echo(root_ctx.get_help())
        return
    command = root_ctx.command.commands.get(name)
    if command is None:
        ui.error(f"未知命令: {name}，可执行 dev help 查看全部命令")
        raise typer.Exit(code=1)
    command_ctx = click.Context(command, info_name=name, parent=root_ctx)
    if not subcommand:
        typer.echo(command.get_help(command_ctx))
        return
    nested = getattr(command, "commands", {}).get(subcommand)
    if nested is None:
        ui.error(f"未知子命令: {name} {subcommand}")
        raise typer.Exit(code=1)
    nested_ctx = click.Context(nested, info_name=subcommand, parent=command_ctx)
    typer.echo(nested.get_help(nested_ctx))


def main() -> None:
    try:
        app(prog_name="dev")
    except (ServiceError, InstallError, ProjectError, DatabaseError, BackupError, RuntimeError, ValueError, OSError) as exc:
        ui.error(str(exc))
        sys.exit(1)
    except KeyboardInterrupt:
        ui.warn("已中断")
        sys.exit(130)


if __name__ == "__main__":
    main()
