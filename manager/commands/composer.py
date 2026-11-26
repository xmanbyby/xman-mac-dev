"""Composer 命令。"""
from __future__ import annotations

import typer

from commands import ui
from providers.composer import ComposerProvider

app = typer.Typer(help="Composer 管理", no_args_is_help=True)


@app.command("install")
def install_cmd() -> None:
    ComposerProvider().install()


@app.command("version")
def version_cmd() -> None:
    typer.echo(ComposerProvider().version())


@app.command("diagnose")
def diagnose_cmd() -> None:
    code = ComposerProvider().diagnose()
    if code != 0:
        raise typer.Exit(code=code)


@app.command("doctor")
def doctor_cmd() -> None:
    from core.doctor import Doctor

    provider = ComposerProvider()
    ui.kv("Composer", provider.info())
    ui.checks_table([item for item in Doctor().run("composer")])
