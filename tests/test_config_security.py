from __future__ import annotations

from pathlib import Path

import pytest

import rhx.config as config_module
from rhx.config import AppConfig, RuntimeConfig, RuntimePaths, ensure_dirs, env_or_none, load_runtime_config, save_runtime_config
from rhx.errors import CLIError, ErrorCode


def test_load_runtime_config_rejects_symlinked_config_file(tmp_path: Path):
    real_cfg = tmp_path / "real.toml"
    real_cfg.write_text('profile = "default"\n')
    cfg_link = tmp_path / "config.toml"
    cfg_link.symlink_to(real_cfg)

    with pytest.raises(CLIError) as exc:
        load_runtime_config(
            config_path=cfg_link,
            profile="default",
            state_db_path=tmp_path / "state" / "state.db",
            session_dir=tmp_path / "sessions",
        )
    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_ensure_dirs_rejects_symlinked_session_dir(tmp_path: Path):
    real_sessions = tmp_path / "real-sessions"
    real_sessions.mkdir()
    session_link = tmp_path / "sessions"
    session_link.symlink_to(real_sessions)

    paths = RuntimePaths(
        config_path=tmp_path / "cfg" / "config.toml",
        state_db_path=tmp_path / "state" / "state.db",
        session_dir=session_link,
    )
    with pytest.raises(CLIError) as exc:
        ensure_dirs(paths)
    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_save_runtime_config_sets_strict_permissions(tmp_path: Path):
    config_path = tmp_path / "cfg" / "config.toml"
    state_db_path = tmp_path / "state" / "state.db"
    session_dir = tmp_path / "sessions"

    runtime = RuntimeConfig(
        app=AppConfig(profile="default"),
        paths=RuntimePaths(
            config_path=config_path,
            state_db_path=state_db_path,
            session_dir=session_dir,
        ),
    )
    save_runtime_config(runtime)

    assert config_path.exists()
    assert (config_path.stat().st_mode & 0o777) == 0o600
    assert (config_path.parent.stat().st_mode & 0o777) == 0o700


def test_load_runtime_config_creates_defaults_with_strict_paths(tmp_path: Path):
    config_path = tmp_path / "cfg" / "config.toml"
    session_dir = tmp_path / "sessions"
    state_db_path = tmp_path / "state" / "state.db"

    runtime = load_runtime_config(
        config_path=config_path,
        profile="work",
        state_db_path=state_db_path,
        session_dir=session_dir,
    )

    assert runtime.app.profile == "work"
    assert config_path.exists()
    assert (config_path.stat().st_mode & 0o777) == 0o600
    assert (session_dir.stat().st_mode & 0o777) == 0o700
    assert (state_db_path.parent.stat().st_mode & 0o777) == 0o700


def test_secure_dir_owner_mismatch_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    target = tmp_path / "owned-dir"
    target.mkdir()
    owner = target.stat().st_uid
    monkeypatch.setattr(config_module.os, "getuid", lambda: owner + 1)

    with pytest.raises(CLIError) as exc:
        config_module._secure_dir(target)
    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_secure_file_owner_mismatch_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    target = tmp_path / "owned.toml"
    target.write_text("x=1\n")
    owner = target.stat().st_uid
    monkeypatch.setattr(config_module.os, "getuid", lambda: owner + 1)

    with pytest.raises(CLIError) as exc:
        config_module._secure_file(target)
    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_env_or_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("RHX_TEST_KEY", raising=False)
    assert env_or_none("RHX_TEST_KEY") is None

    monkeypatch.setenv("RHX_TEST_KEY", "value")
    assert env_or_none("RHX_TEST_KEY") == "value"
