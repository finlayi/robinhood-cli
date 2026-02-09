from __future__ import annotations

from rhx.errors import CLIError, ErrorCode
from rhx.output import emit_error, emit_success, map_unexpected_error


class Recorder:
    def __init__(self):
        self.calls = []

    def print(self, value):
        self.calls.append(value)


def test_emit_success_and_error_non_json(monkeypatch):
    out = Recorder()
    err = Recorder()
    monkeypatch.setattr("rhx.output.stdout_console", out)
    monkeypatch.setattr("rhx.output.stderr_console", err)

    emit_success("cmd", {"x": 1}, json_mode=False, provider="brokerage")
    assert out.calls

    cli_err = CLIError(code=ErrorCode.AUTH_REQUIRED, message="no auth")
    emit_error(cli_err, "cmd", json_mode=False, provider="brokerage")
    assert err.calls


def test_map_unexpected_error():
    exc = RuntimeError("boom")
    mapped = map_unexpected_error(exc)
    assert mapped.code == ErrorCode.INTERNAL_ERROR
    assert "boom" in mapped.message
