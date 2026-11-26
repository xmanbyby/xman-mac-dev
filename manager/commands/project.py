"""项目管理命令。"""
from __future__ import annotations

from typing import Optional

import typer

from commands import ui
from core.project import ProjectManager
from providers.nginx import NginxProvider
from providers.php import PHPProvider

app = typer.Typer(help="项目管理", no_args_is_help=True)


@app.command("add")
def add_cmd(
    name: str = typer.Argument(...),
    path: Optional[str] = typer.Option(None, "--path", help="项目目录，默认 $PROJECTS_HOME/<name>"),
    project_type: Optional[str] = typer.Option(None, "--type", help="laravel/symfony/php/react/vue/vite/node/static"),
    domain: Optional[str] = typer.Option(None, "--domain", help="域名，默认 <name>.local"),
    php_version: Optional[str] = typer.Option(None, "--php", help="PHP 版本"),
    port: Optional[int] = typer.Option(None, "--port", help="Node 开发服务器端口"),
) -> None:
    """注册项目并生成 Nginx 配置。"""
    ProjectManager().add(name, path=path, project_type=project_type, domain=domain,
                         php=php_version, port=port)


@app.command("remove")
def remove_cmd(name: str) -> None:
    """移除项目配置（不删除源码）。"""
    ProjectManager().remove(name)


@app.command("list")
def list_cmd() -> None:
    """列出项目。"""
    projects = ProjectManager().projects()
    if not projects:
        ui.warn("尚未注册项目，执行: dev project add <name>")
        return
    rows = []
    for project in projects:
        rows.append([
            project.get("name", ""),
            project.get("type", ""),
            project.get("domain", ""),
            project.get("php", "") or project.get("port", ""),
            "是" if project.get("enabled", True) else "否",
        ])
    ui.table("项目列表", ["名称", "类型", "域名", "PHP/端口", "启用"], rows)


@app.command("info")
def info_cmd(name: str) -> None:
    """查看项目详情。"""
    ui.kv(f"项目 {name}", ProjectManager().info(name))


@app.command("php")
def php_cmd(name: str, version: str) -> None:
    """设置项目使用的 PHP 版本。"""
    manager = ProjectManager()
    php = PHPProvider()
    if not php.is_installed(version):
        ui.error(f"PHP {version} 未安装")
        raise typer.Exit(code=1)
    manager.set_php(name, version)
    if NginxProvider().running():
        NginxProvider().reload()


@app.command("config")
def config_cmd(name: str) -> None:
    """重新生成项目的 Nginx 配置。"""
    manager = ProjectManager()
    project = manager.find(name)
    path = manager.write_nginx(project)
    ui.ok(f"已生成: {path}")
    nginx = NginxProvider()
    if nginx.running():
        if nginx.reload():
            ui.ok("Nginx 已重载")


@app.command("start")
def start_cmd(name: str) -> None:
    """启动项目（PHP 项目确保 FPM 与 Nginx，Node 项目启动开发服务器）。"""
    ProjectManager().start(name)


@app.command("stop")
def stop_cmd(name: str) -> None:
    """停止项目。"""
    ProjectManager().stop(name)


@app.command("sync-env")
def sync_env_cmd(name: str) -> None:
    """将数据库/缓存连接信息同步到项目 .env。"""
    ProjectManager().sync_env(name)


@app.command("doctor")
def doctor_cmd() -> None:
    """项目诊断。"""
    issues = ProjectManager().doctor()
    if not issues:
        ui.ok("全部项目检查通过")
        return
    for issue in issues:
        ui.warn(issue)
