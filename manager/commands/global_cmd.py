"""全局生命周期命令。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import typer

from commands import ui
from core.backup import BackupError, BackupManager
from core.config import get_config
from core.doctor import Doctor
from core.manager import COMPONENTS, Manager
from core.project import ProjectManager
from core.state import get_state

app = typer.Typer(help="DevEnvironment 全局命令", no_args_is_help=True)


@app.command("init")
def init_cmd() -> None:
    """初始化目录、.env 与状态文件（幂等）。"""
    config = get_config()
    config.init_layout()
    get_state().init_files()
    bin_file = config.home / "bin" / "dev"
    if bin_file.exists():
        os.chmod(bin_file, 0o755)
    ui.ok(f"环境目录已就绪: {config.home}")
    ui.kv("初始化结果", {
        "配置文件": str(config.env_path),
        "配置目录": str(config.config_dir),
        "数据目录": str(config.data_dir),
        "运行目录": str(config.run_dir),
        "日志目录": str(config.logs_dir),
        "状态目录": str(config.state_dir),
        "项目根目录": str(config.projects_home),
    })
    if str(config.home / "bin") not in os.environ.get("PATH", ""):
        ui.warn(f"请将 {config.home}/bin 加入 PATH，之后可直接使用 dev 命令")


@app.command("version")
def version_cmd() -> None:
    """显示管理器版本。"""
    typer.echo("DevEnvironment dev 1.0.0 (macOS native)")


@app.command("status")
def status_cmd() -> None:
    """查看所有服务运行状态。"""
    rows = Manager().status_rows()
    ui.table("服务状态", ["服务", "状态", "版本", "地址", "PID"], [[
        row["服务"], row["状态"], row["版本"], row["地址"], row["PID"]
    ] for row in rows])
    running = sum(1 for row in rows if row["状态"] == "running")
    ui.console.print(f"运行中 {running} / {len(rows)} 个服务")
    if running == 0:
        ui.warn("所有服务均未运行，可执行: dev up")


@app.command("info")
def info_cmd() -> None:
    """查看环境概要信息。"""
    ui.kv("环境信息", Manager().info())


@app.command("doctor")
def doctor_cmd() -> None:
    """环境诊断。"""
    checks = Doctor().run()
    fails, _ = ui.checks_table(checks)
    if fails:
        raise typer.Exit(code=1)


@app.command("install")
def install_cmd(
    all_components: bool = typer.Option(False, "--all", help="安装整套环境"),
    components: Optional[List[str]] = typer.Argument(None, help="指定组件: php nginx mysql redis node composer"),
    skip_extensions: bool = typer.Option(False, "--skip-extensions", help="跳过 PHP 默认扩展"),
) -> None:
    """安装开发环境组件（可重复执行）。"""
    if all_components or not components:
        targets = list(COMPONENTS)
    else:
        targets = [item for item in components if item in COMPONENTS]
        invalid = [item for item in components if item not in COMPONENTS]
        if invalid:
            ui.warn("忽略未知组件: " + ", ".join(invalid))
    ui.console.print("开始安装: " + ", ".join(targets))
    results = Manager().install_all(targets, with_extensions=not skip_extensions)
    success = ui.results_table("安装结果", results)
    if not success:
        raise typer.Exit(code=1)
    ui.console.print("下一步: dev up")


def _resolve_log(target: str) -> Path:
    config = get_config()
    name, _, sub = target.partition(":")
    name, sub = name.strip(), sub.strip()
    if name == "nginx":
        if sub in ("", "error"):
            return config.logs_dir / "nginx" / "error.log"
        if sub == "access":
            return config.logs_dir / "nginx" / "access.log"
        raise ValueError(f"未知 nginx 日志: {sub}，可选 error/access")
    if name == "redis":
        return config.logs_dir / "redis" / "redis.log"
    if name == "php":
        if sub == "slow":
            version = get_state().versions().get("php_cli") or "8.3"
            return config.logs_dir / "php" / version / "php-fpm-slow.log"
        version = sub or get_state().versions().get("php_cli") or "8.3"
        return config.logs_dir / "php" / version / "php-fpm-error.log"
    if name == "mysql":
        from providers.mysql import MySQLProvider

        provider = MySQLProvider()
        if sub == "slow":
            version = provider.active_version() or provider.current_version()
            return config.logs_dir / "mysql" / version / "slow.log"
        version = sub or provider.active_version() or provider.current_version()
        return config.logs_dir / "mysql" / version / "error.log"
    raise ValueError(
        "未知日志目标，可用: nginx[:access] / php[:版本|:slow] / mysql[:版本|:slow] / redis"
    )


def _available_logs() -> List[Path]:
    logs_dir = get_config().logs_dir
    if not logs_dir.exists():
        return []
    return sorted(path for path in logs_dir.rglob("*.log") if path.is_file())


@app.command("logs")
def logs_cmd(
    target: str = typer.Argument("nginx", help="nginx[:access] | php[:8.3|:slow] | mysql[:8.0|:slow] | redis"),
    lines: int = typer.Option(50, "-n", "--lines", min=1, help="显示行数"),
    follow: bool = typer.Option(False, "-f", "--follow", help="持续输出（Ctrl+C 退出）"),
) -> None:
    """查看服务日志，例如: dev logs mysql / dev logs nginx:access -f"""
    try:
        path = _resolve_log(target)
    except ValueError as exc:
        ui.error(str(exc))
        raise typer.Exit(code=1) from exc
    if not path.exists():
        ui.warn(f"日志文件不存在: {path}")
        others = _available_logs()
        if others:
            typer.echo("可用日志:")
            for item in others:
                typer.echo(f"  {item.relative_to(get_config().logs_dir)}")
        raise typer.Exit(code=1)
    typer.echo(f"{path}（最近 {lines} 行）")
    if follow:
        os.execvp("tail", ["tail", "-n", str(lines), "-f", str(path)])
    content = path.read_text(errors="replace").splitlines()
    typer.echo("\n".join(content[-lines:]))


@app.command("uninstall")
def uninstall_cmd(
    components: Optional[List[str]] = typer.Argument(
        None, help="组件，可带版本: php php:8.3 mysql mysql:8.4 nginx redis node composer"
    ),
    all_components: bool = typer.Option(False, "--all", help="卸载所有由管理器安装的软件"),
    yes: bool = typer.Option(False, "--yes", help="跳过确认"),
) -> None:
    """批量卸载指定组件，保留数据与配置。"""
    if all_components:
        targets = list(COMPONENTS)
    elif components:
        targets = []
        for token in components:
            name = token.partition(":")[0]
            if name not in COMPONENTS:
                ui.warn(f"忽略未知组件: {token}（可选: {', '.join(COMPONENTS)}）")
                continue
            targets.append(token)
        if not targets:
            raise typer.Exit(code=1)
    else:
        ui.error("请指定要卸载的组件，或使用 dev uninstall --all")
        raise typer.Exit(code=1)
    if not yes and not ui.confirm(f"确认卸载 {', '.join(targets)}？数据、项目源码与配置将保留。"):
        raise typer.Exit(code=0)
    results = Manager().uninstall(targets)
    success = ui.results_table("卸载结果", results)
    if not success:
        raise typer.Exit(code=1)


PURGE_TARGETS = ("logs", "data", "config", "state", "backups", "all")


@app.command("purge")
def purge_cmd(
    targets: Optional[List[str]] = typer.Argument(
        None, help="清理目标: logs data config state backups all（默认 logs）"
    ),
    all_components: bool = typer.Option(False, "--all", help="等同 dev purge all"),
    yes: bool = typer.Option(False, "--yes", help="跳过确认（data/config/state/backups/all 需要）"),
) -> None:
    """选择性清理：默认仅清空日志。"""
    if all_components:
        selected = ["all"]
    else:
        selected: List[str] = []
        for token in targets or ["logs"]:
            name = token.strip()
            if name not in PURGE_TARGETS:
                ui.warn(f"忽略未知目标: {name}（可选: {', '.join(PURGE_TARGETS)}）")
                continue
            if name not in selected:
                selected.append(name)
        if not selected:
            raise typer.Exit(code=1)
        if "all" in selected:
            selected = ["all"]

    if selected != ["logs"] and not yes:
        descriptions = {
            "data": "MySQL/Redis 数据",
            "config": "生成的配置",
            "state": "状态记录",
            "backups": "所有备份",
            "all": "软件、数据、配置、日志、状态与备份",
        }
        detail = "、".join(descriptions[item] for item in selected)
        ui.warn(f"将删除：{detail}，且不可恢复。")
        if not ui.confirm("确认继续？"):
            raise typer.Exit(code=0)
        if "all" in selected and not ui.confirm("再次确认：确定彻底清理整套环境？"):
            raise typer.Exit(code=0)

    results = Manager().purge(selected)
    success = ui.results_table("清理结果", results)
    if not success:
        raise typer.Exit(code=1)


SERVICE_NAMES = ("mysql", "redis", "php", "nginx")


def _parse_only(only: Optional[str]) -> Optional[List[str]]:
    if not only:
        return None
    return [item.strip() for item in only.split(",") if item.strip()]


def _services(
    services: Optional[List[str]] = None,
    only: Optional[str] = None,
) -> Optional[List[str]]:
    """合并位置参数与 --only，去重并校验；无输入时返回 None 表示全部。"""
    items: List[str] = []
    for item in services or []:
        items.extend(part.strip() for part in item.split(",") if part.strip())
    items.extend(_parse_only(only) or [])
    if not items:
        return None
    ordered: List[str] = []
    for name in items:
        if name not in SERVICE_NAMES:
            ui.warn(f"忽略不支持的服务: {name}（可选: {', '.join(SERVICE_NAMES)}）")
            continue
        if name not in ordered:
            ordered.append(name)
    if not ordered:
        ui.error("未指定有效服务")
        raise typer.Exit(code=1)
    return ordered


@app.command("up")
def up_cmd(
    services: Optional[List[str]] = typer.Argument(None, help="服务: mysql redis php nginx"),
    only: Optional[str] = typer.Option(None, "--only", help="逗号分隔，如 mysql,redis,nginx"),
) -> None:
    """按依赖顺序启动全部或指定服务。"""
    results = Manager().up(_services(services, only))
    success = ui.results_table("启动结果", results)
    if not success:
        ui.warn("部分服务启动失败，请查看上方错误或 dev doctor")
        raise typer.Exit(code=1)


@app.command("start")
def start_cmd(
    services: Optional[List[str]] = typer.Argument(None, help="服务: mysql redis php nginx"),
) -> None:
    """批量启动指定服务（dev up 的别名）。"""
    results = Manager().up(_services(services))
    success = ui.results_table("启动结果", results)
    if not success:
        raise typer.Exit(code=1)


@app.command("down")
def down_cmd(
    services: Optional[List[str]] = typer.Argument(None, help="服务: mysql redis php nginx"),
    only: Optional[str] = typer.Option(None, "--only", help="逗号分隔，如 mysql,redis"),
) -> None:
    """按依赖逆序停止全部或指定服务。"""
    results = Manager().down(_services(services, only))
    ui.results_table("停止结果", results)


@app.command("stop")
def stop_cmd(
    services: Optional[List[str]] = typer.Argument(None, help="服务: mysql redis php nginx"),
) -> None:
    """批量停止指定服务（dev down 的别名）。"""
    results = Manager().down(_services(services))
    ui.results_table("停止结果", results)


@app.command("restart")
def restart_cmd(
    services: Optional[List[str]] = typer.Argument(None, help="服务: mysql redis php nginx"),
    only: Optional[str] = typer.Option(None, "--only", help="逗号分隔，如 mysql,redis"),
) -> None:
    """重启全部或指定服务。"""
    results = Manager().restart(_services(services, only))
    success = ui.results_table("重启结果", results)
    if not success:
        raise typer.Exit(code=1)


@app.command("enable")
def enable_cmd(
    name: str = typer.Argument(..., help="nginx / mysql / redis / php"),
    version: Optional[str] = typer.Option(None, "--version", help="PHP 版本，如 8.3"),
) -> None:
    """纳入 dev up 的自动启动范围。"""
    Manager().set_enabled(name, True, version)


@app.command("disable")
def disable_cmd(
    name: str = typer.Argument(..., help="nginx / mysql / redis / php"),
    version: Optional[str] = typer.Option(None, "--version", help="PHP 版本，如 8.3"),
) -> None:
    """移出 dev up 的自动启动范围（不卸载）。"""
    Manager().set_enabled(name, False, version)


@app.command("backup")
def backup_cmd(target: str = typer.Argument("all", help="all / config / mysql / redis")) -> None:
    """备份配置与数据。"""
    manager = BackupManager()
    if target == "all":
        for key, value in manager.backup_all().items():
            ui.ok(f"{key}: {value}")
    elif target == "config":
        manager.backup_config()
    elif target == "mysql":
        manager.backup_mysql()
    elif target == "redis":
        manager.backup_redis()
    else:
        ui.error(f"未知备份目标: {target}")


@app.command("restore")
def restore_cmd(
    target: str = typer.Argument("config", help="config / mysql / redis"),
    file: Optional[str] = typer.Option(None, "--file", help="指定备份文件或目录，默认使用最新备份"),
    yes: bool = typer.Option(False, "--yes", help="跳过确认"),
) -> None:
    """从备份恢复配置或数据。"""
    manager = BackupManager()
    if not yes and not ui.confirm(f"确认恢复 {target}？现有数据可能被覆盖。"):
        raise typer.Exit(code=0)
    if target == "config":
        if file:
            archive = Path(file).expanduser()
        else:
            items = sorted((get_config().backups_dir / "config").glob("*.tar.gz"), reverse=True)
            if not items:
                raise BackupError("没有可用配置备份")
            archive = items[0]
        manager.restore_config(archive)
    elif target == "mysql":
        if file:
            dump = Path(file).expanduser()
        else:
            items = sorted((get_config().backups_dir / "mysql").glob("*/all-databases.sql"), reverse=True)
            if not items:
                raise BackupError("没有可用 MySQL 备份")
            dump = items[0]
        manager.restore_mysql(dump)
    elif target == "redis":
        if file:
            folder = Path(file).expanduser()
        else:
            items = sorted([item for item in (get_config().backups_dir / "redis").iterdir() if item.is_dir()], reverse=True)
            if not items:
                raise BackupError("没有可用 Redis 备份")
            folder = items[0]
        manager.restore_redis(folder)
    else:
        ui.error(f"未知恢复目标: {target}")
