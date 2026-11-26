"""命令层通用输出。"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import typer
from rich.console import Console
from rich.table import Table

console = Console()


def table(title: str, columns: Sequence[str], rows: Sequence[Sequence[str]]) -> None:
    grid = Table(title=title, show_header=True, header_style="bold cyan", expand=False)
    for column in columns:
        grid.add_column(column)
    for row in rows:
        grid.add_row(*[str(item) for item in row])
    console.print(grid)


def kv(title: str, data: Dict[str, str]) -> None:
    table(title, ["项目", "值"], [[key, value] for key, value in data.items()])


def results_table(title: str, results: Sequence[Tuple[str, bool, str]]) -> bool:
    rows = [["✔" if ok else "✘", name, detail] for name, ok, detail in results]
    table(title, ["", "组件", "结果"], rows)
    return all(ok for _, ok, _ in results)


def checks_table(checks) -> Tuple[int, int]:
    styles = {"ok": "green", "warn": "yellow", "fail": "red"}
    rows = []
    for check in checks:
        mark = {"ok": "✔", "warn": "!", "fail": "✘"}[check.status]
        advice = check.advice or ""
        rows.append([f"[{styles[check.status]}]{mark}[/]", check.name, check.detail, advice])
    table("环境诊断", ["", "检查项", "结果", "建议"], rows)
    fails = sum(1 for item in checks if item.status == "fail")
    warns = sum(1 for item in checks if item.status == "warn")
    console.print(f"通过 {len(checks) - fails - warns} 项，警告 {warns} 项，失败 {fails} 项")
    return fails, warns


def ok(message: str) -> None:
    console.print(f"[green]✔[/] {message}")


def warn(message: str) -> None:
    console.print(f"[yellow]![/] {message}")


def error(message: str) -> None:
    console.print(f"[red]✘[/] {message}")


def confirm(message: str) -> bool:
    return typer.confirm(message, default=False)
