"""Redis 命令。"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional

import typer

from commands import ui
from core.backup import BackupManager
from providers.redis import RedisProvider

app = typer.Typer(help="Redis 管理", no_args_is_help=True)
password_app = typer.Typer(help="Redis 密码管理", invoke_without_command=True)
user_app = typer.Typer(help="Redis ACL 用户管理", no_args_is_help=True)
app.add_typer(password_app, name="password")
app.add_typer(user_app, name="user")


def _provider() -> RedisProvider:
    return RedisProvider()


def _prompt_password() -> str:
    return typer.prompt("新密码", hide_input=True, confirmation_prompt=True)


@app.command("install")
def install_cmd() -> None:
    """安装 Redis。"""
    _provider().install()


@app.command("uninstall")
def uninstall_cmd() -> None:
    """卸载 Redis（保留数据）。"""
    _provider().uninstall()


@app.command("start")
def start_cmd() -> None:
    _provider().start()


@app.command("stop")
def stop_cmd() -> None:
    _provider().stop()


@app.command("restart")
def restart_cmd() -> None:
    _provider().restart()


@app.command("status")
def status_cmd() -> None:
    ui.kv("Redis 状态", _provider().info())


@app.command("list")
def list_cmd() -> None:
    """查看 Redis 信息（兼容 dev redis list）。"""
    ui.kv("Redis", _provider().info())


@app.command("info")
def info_cmd() -> None:
    ui.kv("Redis", _provider().info())


@password_app.callback()
def password_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _provider().set_password(_prompt_password())
        ui.ok("密码已更新")


@password_app.command("init")
def init_cmd() -> None:
    """生成随机密码并写入 Keychain。"""
    provider = _provider()
    if provider.running():
        from core.database import RedisClient

        if RedisClient().ping():
            ui.ok("已设置密码且连接正常，无需初始化")
            return
    provider.init_password()
    ui.ok("Redis 密码已初始化 (Keychain: dev.redis.default)")


@user_app.command("create")
def user_create(name: str, password: Optional[str] = typer.Option(None, "--password")) -> None:
    """创建 ACL 用户。"""
    _provider().create_user(name, password or _prompt_password())


@user_app.command("password")
def user_password(name: str) -> None:
    """修改 ACL 用户密码。"""
    _provider().set_user_password(name, _prompt_password())


@user_app.command("delete")
def user_delete(name: str, yes: bool = typer.Option(False, "--yes")) -> None:
    if not yes and not ui.confirm(f"确认删除 Redis 用户 {name}？"):
        raise typer.Exit(code=0)
    _provider().delete_user(name)


@user_app.command("list")
def user_list() -> None:
    users = _provider().list_users()
    ui.table("Redis ACL 用户", ["用户"], [[item] for item in users])


@app.command("backup")
def backup_cmd() -> None:
    """备份 RDB / AOF。"""
    BackupManager().backup_redis()


@app.command("restore")
def restore_cmd(folder: Optional[str] = typer.Argument(None), yes: bool = typer.Option(False, "--yes")) -> None:
    """从备份目录恢复。"""
    if folder:
        target = Path(folder).expanduser()
    else:
        items = sorted([item for item in (_provider().config.backups_dir / "redis").iterdir() if item.is_dir()], reverse=True)
        if not items:
            ui.error("没有可用备份")
            raise typer.Exit(code=1)
        target = items[0]
    if not yes and not ui.confirm(f"确认从 {target} 恢复？现有数据将被替换。"):
        raise typer.Exit(code=0)
    BackupManager().restore_redis(target)


@app.command("doctor")
def doctor_cmd() -> None:
    from core.doctor import Doctor

    ui.checks_table(Doctor().run("redis"))
