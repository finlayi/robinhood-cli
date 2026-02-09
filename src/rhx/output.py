from __future__ import annotations

import json
from typing import Any

import typer
from rich.console import Console
from rich.pretty import Pretty

from rhx.errors import CLIError, ErrorCode
from rhx.models import OutputEnvelope


stdout_console = Console(stderr=False)
stderr_console = Console(stderr=True)


def emit_success(command: str, data: dict[str, Any] | list[Any] | None, json_mode: bool, provider: str | None) -> None:
    envelope = OutputEnvelope.success(command=command, data=data, provider=provider)
    if json_mode:
        typer.echo(envelope.model_dump_json())
        return
    stdout_console.print(f"[green]OK[/green] {command}")
    if data is not None:
        stdout_console.print(Pretty(data))


def emit_error(err: CLIError, command: str, json_mode: bool, provider: str | None) -> None:
    envelope = OutputEnvelope.failure(
        command=command,
        code=err.code.value,
        message=err.message,
        retriable=err.retriable,
        provider=provider,
    )
    if json_mode:
        typer.echo(envelope.model_dump_json())
        return
    stderr_console.print(f"[red]{err.code.value}[/red] {err.message}")


def map_unexpected_error(exc: Exception) -> CLIError:
    return CLIError(code=ErrorCode.INTERNAL_ERROR, message=str(exc), retriable=False)
