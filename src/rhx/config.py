from __future__ import annotations

import os
import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel, Field

from rhx.errors import CLIError, ErrorCode


def default_config_path() -> Path:
    return Path.home() / ".config" / "robinhood-cli" / "config.toml"


def default_state_db_path() -> Path:
    return Path.home() / ".local" / "share" / "robinhood-cli" / "state.db"


def default_session_dir() -> Path:
    return Path.home() / ".config" / "robinhood-cli" / "sessions"


class SafetyConfig(BaseModel):
    live_mode: bool = False
    live_unlock_ttl_seconds: int = 900
    max_order_notional: float | None = None
    max_daily_notional: float | None = None
    allow_symbols: list[str] = Field(default_factory=list)
    block_symbols: list[str] = Field(default_factory=list)
    trading_window: str | None = None


class AppConfig(BaseModel):
    profile: str = "default"
    provider_default: str = "auto"
    safety: SafetyConfig = Field(default_factory=SafetyConfig)


class RuntimePaths(BaseModel):
    config_path: Path
    state_db_path: Path
    session_dir: Path


class RuntimeConfig(BaseModel):
    app: AppConfig
    paths: RuntimePaths


def ensure_dirs(paths: RuntimePaths) -> None:
    _secure_dir(paths.config_path.parent)
    _secure_dir(paths.state_db_path.parent)
    _secure_dir(paths.session_dir)


def _secure_dir(path: Path) -> None:
    if path.exists() and path.is_symlink():
        raise CLIError(code=ErrorCode.AUTH_REQUIRED, message=f"Refusing symlinked directory: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    st = path.stat()
    if st.st_uid != os.getuid():
        raise CLIError(code=ErrorCode.AUTH_REQUIRED, message=f"Directory is not owned by current user: {path}")


def _secure_file(path: Path) -> None:
    if path.is_symlink():
        raise CLIError(code=ErrorCode.AUTH_REQUIRED, message=f"Refusing symlinked file: {path}")
    st = path.stat()
    if st.st_uid != os.getuid():
        raise CLIError(code=ErrorCode.AUTH_REQUIRED, message=f"File is not owned by current user: {path}")
    os.chmod(path, 0o600)


def load_runtime_config(
    config_path: Path | None = None,
    profile: str = "default",
    state_db_path: Path | None = None,
    session_dir: Path | None = None,
) -> RuntimeConfig:
    cfg_path = config_path or default_config_path()
    db_path = state_db_path or default_state_db_path()
    sess_dir = session_dir or default_session_dir()

    paths = RuntimePaths(config_path=cfg_path, state_db_path=db_path, session_dir=sess_dir)
    ensure_dirs(paths)

    if not cfg_path.exists():
        app_cfg = AppConfig(profile=profile)
        runtime = RuntimeConfig(app=app_cfg, paths=paths)
        save_runtime_config(runtime)
        return runtime

    _secure_file(cfg_path)
    with cfg_path.open("rb") as fh:
        raw = tomllib.load(fh)

    app_cfg = AppConfig.model_validate(raw or {})
    if profile:
        app_cfg.profile = profile

    return RuntimeConfig(app=app_cfg, paths=paths)


def save_runtime_config(config: RuntimeConfig) -> None:
    _secure_dir(config.paths.config_path.parent)
    payload = config.app.model_dump(mode="python", exclude_none=True)
    with config.paths.config_path.open("wb") as fh:
        fh.write(tomli_w.dumps(payload).encode("utf-8"))
    _secure_file(config.paths.config_path)


def env_or_none(key: str) -> str | None:
    value = os.getenv(key)
    return value if value else None
