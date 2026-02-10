from __future__ import annotations

from typing import Any

import typer
from rich.console import Console
from rich.pretty import Pretty

from rhx.errors import CLIError, ErrorCode
from rhx.models import OutputEnvelope


stdout_console = Console(stderr=False)
stderr_console = Console(stderr=True)


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
) -> None:
    envelope = OutputEnvelope.success(command=command, data=data, provider=provider)
    if json_mode:
        envelope = _with_json_meta(envelope, view=view, meta_updates=meta_updates)
        typer.echo(envelope.model_dump_json())
        return
    stdout_console.print(f"[green]OK[/green] {command}")
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
