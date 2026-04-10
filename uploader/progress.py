from __future__ import annotations

from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn


def create_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.fields[service]}[/bold]"),
        TextColumn("{task.fields[state]}"),
        BarColumn(bar_width=30),
        TaskProgressColumn(),
        TextColumn("{task.fields[speed]}"),
        TimeElapsedColumn(),
        TextColumn("{task.fields[filename]}"),
        transient=False,
    )
