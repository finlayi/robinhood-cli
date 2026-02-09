from __future__ import annotations

from rhx.errors import CLIError, ErrorCode


def test_cli_error_string_and_exit_code():
    err = CLIError(code=ErrorCode.AUTH_REQUIRED, message="missing")
    assert str(err) == "AUTH_REQUIRED: missing"
    assert err.exit_code == 3
