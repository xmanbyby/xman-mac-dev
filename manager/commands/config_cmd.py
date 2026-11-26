"""配置命令。"""
from __future__ import annotations

from typing import Optional

import typer

from commands import ui
from core.config import get_config, reset_config

app = typer.Typer(help="全局配置管理", invoke_without_command=True, no_args_is_help=False)


@app.callback()
def callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        show_all()


def show_all() -> None:
    config = get_config()
    ui.table("全局配置 (.env)", ["配置项", "值"],
             [[key, value] for key, value in config.as_dict().items()])
    ui.console.print(f"配置文件: {config.env_path}")


@app.command("get")
def get_cmd(key: str) -> None:
    """读取单个配置项。"""
    config = get_config()
    typer.echo(config.get(key))


@app.command("set")
def set_cmd(key: str, value: str) -> None:
    """修改配置项（自动写回 .env）。"""
    config = get_config()
    config.set_env(key, value)
    ui.ok(f"{key} = {value}")
    issues = config.validate()
    for level, message in issues:
        (ui.error if level == "error" else ui.warn)(message)


@app.command("reload")
def reload_cmd() -> None:
    """重新加载配置并刷新快照。"""
    config = reset_config()
    config.save_snapshot()
    ui.ok("配置已重新加载")
    show_all()


@app.command("validate")
def validate_cmd() -> None:
    """校验配置。"""
    issues = get_config().validate()
    if not issues:
        ui.ok("配置校验通过")
        return
    for level, message in issues:
        (ui.error if level == "error" else ui.warn)(message)
    if any(level == "error" for level, _ in issues):
        raise typer.Exit(code=1)
