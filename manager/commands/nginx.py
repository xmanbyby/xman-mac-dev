"""Nginx 命令。"""
from __future__ import annotations

import typer

from commands import ui
from providers.nginx import NginxProvider

app = typer.Typer(help="Nginx 管理", no_args_is_help=True)
provider = NginxProvider


@app.command("install")
def install_cmd() -> None:
    """安装 Nginx。"""
    provider().install()


@app.command("start")
def start_cmd() -> None:
    """启动 Nginx。"""
    provider().start()


@app.command("stop")
def stop_cmd() -> None:
    """停止 Nginx。"""
    provider().stop()


@app.command("restart")
def restart_cmd() -> None:
    """重启 Nginx。"""
    provider().restart()


@app.command("reload")
def reload_cmd() -> None:
    """重载配置。"""
    if not provider().reload():
        raise typer.Exit(code=1)


@app.command("status")
def status_cmd() -> None:
    """查看状态。"""
    nginx = provider()
    ui.kv("Nginx", {
        "安装": "是" if nginx.is_installed() else "否",
        "运行": "running" if nginx.running() else "stopped",
        "可执行文件": nginx.binary(),
        "配置文件": str(nginx.config.nginx_conf),
        "项目配置": ", ".join(nginx.current_conf_has_projects()) or "无",
    })


@app.command("test")
def test_cmd() -> None:
    """检查配置语法。"""
    if not provider().test(verbose=True):
        raise typer.Exit(code=1)


@app.command("doctor")
def doctor_cmd() -> None:
    """Nginx 诊断。"""
    from core.doctor import Doctor

    checks = [item for item in Doctor().run("nginx")]
    ui.checks_table(checks)
