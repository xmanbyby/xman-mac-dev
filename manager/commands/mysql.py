"""MySQL 命令。"""
from __future__ import annotations

import secrets
from pathlib import Path
from typing import Optional

import typer

from commands import ui
from core.backup import BackupManager
from core.database import DatabaseError, MySQLClient
from providers.mysql import MySQLProvider
from utils import security
from utils.filesystem import MYSQL_VERSIONS

app = typer.Typer(help="MySQL 管理", no_args_is_help=True)
password_app = typer.Typer(help="root 密码管理", invoke_without_command=True)
user_app = typer.Typer(help="数据库用户管理", no_args_is_help=True)
database_app = typer.Typer(help="数据库管理", no_args_is_help=True)
app.add_typer(password_app, name="password")
app.add_typer(user_app, name="user")
app.add_typer(database_app, name="database")


def _provider() -> MySQLProvider:
    return MySQLProvider()


def _version(version: Optional[str] = None) -> str:
    provider = _provider()
    resolved = version or provider.active_version() or provider.current_version()
    if not provider.is_installed(resolved):
        ui.error(f"MySQL {resolved} 未安装，请先执行: dev mysql install {resolved}")
        raise typer.Exit(code=1)
    return resolved


def _prompt_password() -> str:
    return typer.prompt("新密码", hide_input=True, confirmation_prompt=True)


@app.command("install")
def install_cmd(version: str = typer.Argument(..., help="8.0 / 8.4")) -> None:
    """安装指定 MySQL 版本。"""
    if version not in MYSQL_VERSIONS:
        ui.error(f"不支持的版本: {version}，可选: {', '.join(MYSQL_VERSIONS)}")
        raise typer.Exit(code=1)
    _provider().install(version)


@app.command("uninstall")
def uninstall_cmd(version: Optional[str] = typer.Argument(None)) -> None:
    """卸载 MySQL（保留数据目录）。"""
    _provider().uninstall(_version(version))


@app.command("list")
def list_cmd() -> None:
    """列出 MySQL 版本。"""
    provider = _provider()
    current = provider.current_version()
    active = provider.active_version()
    rows = []
    for version in MYSQL_VERSIONS:
        installed = provider.is_installed(version)
        rows.append([
            version,
            "已安装" if installed else "-",
            "是" if version == current else "",
            "running" if version == active else "stopped",
            str(provider.config.mysql_data_dir(version)),
        ])
    ui.table("MySQL 版本", ["版本", "安装", "当前", "运行", "数据目录"], rows)


@app.command("info")
def info_cmd(version: Optional[str] = typer.Argument(None)) -> None:
    """查看 MySQL 信息。"""
    ui.kv("MySQL", _provider().info(version))


@app.command("switch")
def switch_cmd(version: str) -> None:
    """切换当前运行的 MySQL 大版本。"""
    _provider().switch(version)


@app.command("upgrade")
def upgrade_cmd(from_version: str = typer.Argument(...), to_version: str = typer.Argument(...)) -> None:
    """逻辑升级：备份旧版本数据并导入新版本。"""
    if to_version not in MYSQL_VERSIONS:
        ui.error(f"不支持的目标版本: {to_version}")
        raise typer.Exit(code=1)
    if not ui.confirm(f"确认从 {from_version} 升级到 {to_version}？将先执行完整备份。"):
        raise typer.Exit(code=0)
    dump = BackupManager().backup_mysql(from_version)
    _provider().upgrade(from_version, to_version, dump)
    ui.ok("升级完成，旧版本数据与备份已保留")


@app.command("start")
def start_cmd(version: Optional[str] = typer.Argument(None)) -> None:
    """启动 MySQL。"""
    _provider().start(version)


@app.command("stop")
def stop_cmd(version: Optional[str] = typer.Argument(None)) -> None:
    """停止 MySQL。"""
    _provider().stop(version)


@app.command("restart")
def restart_cmd(version: Optional[str] = typer.Argument(None)) -> None:
    """重启 MySQL。"""
    _provider().restart(version)


@app.command("status")
def status_cmd() -> None:
    """查看 MySQL 状态。"""
    provider = _provider()
    active = provider.active_version()
    ui.kv("MySQL 状态", {
        "运行": "running" if active else "stopped",
        "运行版本": active or "-",
        "配置版本": provider.current_version(),
        "监听": f"{provider.config.get('MYSQL_HOST')}:{provider.config.get_int('MYSQL_PORT')}",
        "Socket": str(provider.config.mysql_socket(active or provider.current_version())),
        "PID": str(provider.config.mysql_pid(active or provider.current_version())),
    })


# ---------------------------------------------------------------------- password
@password_app.callback()
def password_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        change_root_password()


def change_root_password() -> None:
    version = _version()
    new_password = _prompt_password()
    client = MySQLClient()
    current = client.root_password() or ""
    result = client.execute(version, f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{new_password}'; FLUSH PRIVILEGES;", password=current)
    if not result.ok:
        result = client.execute(version, f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{new_password}'; FLUSH PRIVILEGES;", password="")
    if not result.ok:
        ui.error(f"修改 root 密码失败: {result.brief()}")
        raise typer.Exit(code=1)
    security.keychain_set("mysql.root", new_password)
    if client.ping(version, password=new_password):
        ui.ok("root 密码已更新并写入 Keychain")
    else:
        ui.warn("密码已修改，但连接验证失败，请执行 dev mysql doctor")


@password_app.command("init")
def init_password_cmd() -> None:
    """初始化 root 密码（若为空则自动生成并写入 Keychain）。"""
    provider = _provider()
    version = _version()
    client = MySQLClient()
    stored = client.root_password()
    if stored and client.ping(version, password=stored):
        ui.ok("root 密码已存在且连接正常")
        return
    if client.ping(version, password=""):
        password = stored or secrets.token_urlsafe(18)
        if client.ensure_root_password(version, password):
            ui.ok("root 密码已初始化并写入 Keychain (dev.mysql.root)")
        else:
            ui.error("初始化失败，请查看 MySQL 错误日志")
            raise typer.Exit(code=1)
        return
    ui.warn("无法使用空密码或 Keychain 密码连接，请先确认 MySQL 已启动")
    raise typer.Exit(code=1)


# ---------------------------------------------------------------------- user
@user_app.command("create")
def user_create(name: str = typer.Argument(...), password: Optional[str] = typer.Option(None, "--password")) -> None:
    """创建数据库用户并写入 Keychain。"""
    version = _version()
    pwd = password or _prompt_password()
    MySQLClient().create_user(version, name, pwd)
    ui.ok(f"用户 {name} 已创建（dev.mysql.{name}）")
    if typer.confirm(f"是否为用户 {name} 创建同名数据库？", default=True):
        MySQLClient().create_database(version, name.replace("-", "_"), owner=name)
        ui.ok("数据库已创建并授权")


@user_app.command("password")
def user_password(name: str) -> None:
    """修改数据库用户密码。"""
    MySQLClient().set_user_password(_version(), name, _prompt_password())
    ui.ok(f"用户 {name} 密码已更新")


@user_app.command("delete")
def user_delete(name: str, yes: bool = typer.Option(False, "--yes")) -> None:
    """删除数据库用户。"""
    if not yes and not ui.confirm(f"确认删除用户 {name}？"):
        raise typer.Exit(code=0)
    MySQLClient().delete_user(_version(), name)
    ui.ok(f"用户 {name} 已删除")


@user_app.command("list")
def user_list() -> None:
    """列出数据库用户。"""
    rows = [[user, host] for user, host in MySQLClient().list_users(_version())]
    ui.table("MySQL 用户", ["用户", "Host"], rows)


# ---------------------------------------------------------------------- database
@database_app.command("create")
def database_create(
    name: str,
    owner: Optional[str] = typer.Option(None, "--owner", help="属主用户，不存在时自动创建（密码同用户名）"),
) -> None:
    """创建数据库。"""
    auto_created = MySQLClient().create_database(_version(), name, owner=owner)
    ui.ok(f"数据库 {name} 已创建")
    if auto_created:
        ui.warn(f"用户 {owner} 不存在，已自动创建（密码同用户名，已存入 dev.mysql.{owner}）")
        ui.console.print(f"建议修改密码: dev mysql user password {owner}")


@database_app.command("list")
def database_list() -> None:
    """列出数据库。"""
    rows = [[item] for item in MySQLClient().list_databases(_version())]
    ui.table("MySQL 数据库", ["名称"], rows)


# ---------------------------------------------------------------------- backup
@app.command("backup")
def backup_cmd() -> None:
    """备份 MySQL 全部数据库。"""
    BackupManager().backup_mysql(_version())


@app.command("restore")
def restore_cmd(file: Optional[str] = typer.Argument(None), yes: bool = typer.Option(False, "--yes")) -> None:
    """从 SQL 备份恢复。"""
    if file:
        dump = Path(file).expanduser()
    else:
        items = sorted((_provider().config.backups_dir / "mysql").glob("*/all-databases.sql"), reverse=True)
        if not items:
            ui.error("没有可用备份")
            raise typer.Exit(code=1)
        dump = items[0]
    if not yes and not ui.confirm(f"确认恢复 {dump}？现有同名数据库会被覆盖。"):
        raise typer.Exit(code=0)
    BackupManager().restore_mysql(dump, _version())


@app.command("doctor")
def doctor_cmd() -> None:
    """MySQL 诊断。"""
    from core.doctor import Doctor

    ui.checks_table(Doctor().run("mysql"))
