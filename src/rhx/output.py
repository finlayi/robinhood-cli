from __future__ import annotations

import json
from typing import Any

import typer
from rich.console import Console
from rich.pretty import Pretty
from rich.table import Table

from rhx.errors import CLIError, ErrorCode
from rhx.models import OutputEnvelope
from rhx.output_shape import shape_data


stdout_console = Console(stderr=False)
stderr_console = Console(stderr=True)
HUMAN_ROW_LIMIT = 20


def _format_human_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), sort_keys=True)
    return str(value)


def _render_human_data(data: dict[str, Any] | list[Any] | None, meta: dict[str, Any] | None) -> None:
    if data is None:
        return

    if isinstance(data, dict):
        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_column("field", style="cyan")
        table.add_column("value")
        for key, value in data.items():
            table.add_row(str(key), _format_human_value(value))
        stdout_console.print(table)
        return

    if isinstance(data, list):
        if not data:
            stdout_console.print("[dim](empty)[/dim]")
            return

        if all(isinstance(item, dict) for item in data):
            keys: list[str] = []
            for item in data:
                for key in item:
                    if key not in keys:
                        keys.append(key)

            table = Table()
            for key in keys:
                table.add_column(str(key))
            for item in data:
                table.add_row(*[_format_human_value(item.get(key)) for key in keys])
            stdout_console.print(table)
        else:
            for item in data:
                stdout_console.print(f"- {_format_human_value(item)}")

        if meta and meta.get("truncated"):
            stdout_console.print(
                f"[dim]showing {meta.get('returned_count', '?')} of {meta.get('total_count', '?')} rows[/dim]"
            )
        return

    stdout_console.print(_format_human_value(data))


def _with_json_meta(envelope: OutputEnvelope, view: str, meta_updates: dict[str, Any] | None) -> OutputEnvelope:
    envelope.meta.update({"output_schema": "v2", "view": view})
    if meta_updates:
        envelope.meta.update(meta_updates)
    return envelope


def emit_success(
    command: str,
    data: dict[str, Any] | list[Any] | None,
    json_mode: bool,
    provider: str | None,
    *,
    meta_updates: dict[str, Any] | None = None,
    view: str = "summary",
    human_mode: bool = False,
) -> None:
    envelope = OutputEnvelope.success(command=command, data=data, provider=provider)
    if json_mode:
        envelope = _with_json_meta(envelope, view=view, meta_updates=meta_updates)
        typer.echo(envelope.model_dump_json())
        return
    stdout_console.print(f"[green]OK[/green] {command}")
    if human_mode:
        human_data = data
        human_meta: dict[str, Any] = {}
        try:
            human_data, human_meta = shape_data(
                command=command,
                provider=provider,
                data=data,
                view="summary",
                fields=None,
                limit=HUMAN_ROW_LIMIT,
            )
        except CLIError:
            human_data = data
            human_meta = {}
        _render_human_data(human_data, human_meta)
        return
    if data is not None:
        stdout_console.print(Pretty(data))


def emit_error(
    err: CLIError,
    command: str,
    json_mode: bool,
    provider: str | None,
    *,
    meta_updates: dict[str, Any] | None = None,
    view: str = "summary",
) -> None:
    envelope = OutputEnvelope.failure(
        command=command,
        code=err.code.value,
        message=err.message,
        retriable=err.retriable,
        provider=provider,
    )
    if json_mode:
        envelope = _with_json_meta(envelope, view=view, meta_updates=meta_updates)
        typer.echo(envelope.model_dump_json())
        return
    stderr_console.print(f"[red]{err.code.value}[/red] {err.message}")


def map_unexpected_error(exc: Exception) -> CLIError:
    return CLIError(code=ErrorCode.INTERNAL_ERROR, message=str(exc), retriable=False)
