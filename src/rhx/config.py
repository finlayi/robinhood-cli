from __future__ import annotations

import os
import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel, Field


def default_config_path() -> Path:
    return Path.home() / ".config" / "robinhood-cli" / "config.toml"


def default_state_db_path() -> Path:
    return Path.home() / ".local" / "share" / "robinhood-cli" / "state.db"


def default_session_dir() -> Path:
    return Path.home() / ".config" / "robinhood-cli" / "sessions"


class SafetyConfig(BaseModel):
    live_mode: bool = False
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
    paths.config_path.parent.mkdir(parents=True, exist_ok=True)
    paths.state_db_path.parent.mkdir(parents=True, exist_ok=True)
    paths.session_dir.mkdir(parents=True, exist_ok=True)


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

    with cfg_path.open("rb") as fh:
        raw = tomllib.load(fh)

    app_cfg = AppConfig.model_validate(raw or {})
    if profile:
        app_cfg.profile = profile

    return RuntimeConfig(app=app_cfg, paths=paths)


def save_runtime_config(config: RuntimeConfig) -> None:
    config.paths.config_path.parent.mkdir(parents=True, exist_ok=True)
    payload = config.app.model_dump(mode="python", exclude_none=True)
    with config.paths.config_path.open("wb") as fh:
        fh.write(tomli_w.dumps(payload).encode("utf-8"))


def env_or_none(key: str) -> str | None:
    value = os.getenv(key)
    return value if value else None
