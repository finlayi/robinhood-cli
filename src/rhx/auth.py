from __future__ import annotations

import getpass
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import keyring
from keyring.errors import KeyringError

from rhx.errors import CLIError, ErrorCode
from rhx.models import AuthStatus


BROKERAGE_SERVICE = "rhx.robinhood.brokerage"
CRYPTO_SERVICE = "rhx.robinhood.crypto"
logger = logging.getLogger(__name__)


@dataclass
class CredentialStore:
    def _get(self, service: str, key: str) -> str | None:
        try:
            return keyring.get_password(service, key)
        except KeyringError as exc:
            logger.warning("Keyring read failed for %s:%s: %s", service, key, exc)
            return None

    def _set(self, service: str, key: str, value: str) -> None:
        keyring.set_password(service, key, value)

    def _delete(self, service: str, key: str) -> None:
        try:
            keyring.delete_password(service, key)
        except KeyringError as exc:
            logger.warning("Keyring delete failed for %s:%s: %s", service, key, exc)

    def get_robinhood_credentials(self, profile: str) -> tuple[str | None, str | None]:
        username = self._get(BROKERAGE_SERVICE, f"{profile}:username")
        password = self._get(BROKERAGE_SERVICE, f"{profile}:password")
        return username, password

    def set_robinhood_credentials(self, profile: str, username: str, password: str) -> None:
        self._set(BROKERAGE_SERVICE, f"{profile}:username", username)
        self._set(BROKERAGE_SERVICE, f"{profile}:password", password)

    def delete_robinhood_credentials(self, profile: str) -> None:
        self._delete(BROKERAGE_SERVICE, f"{profile}:username")
        self._delete(BROKERAGE_SERVICE, f"{profile}:password")

    def get_crypto_credentials(self, profile: str) -> tuple[str | None, str | None]:
        api_key = self._get(CRYPTO_SERVICE, f"{profile}:api_key")
        private_key_b64 = self._get(CRYPTO_SERVICE, f"{profile}:private_key_b64")
        return api_key, private_key_b64

    def set_crypto_credentials(self, profile: str, api_key: str, private_key_b64: str) -> None:
        self._set(CRYPTO_SERVICE, f"{profile}:api_key", api_key)
        self._set(CRYPTO_SERVICE, f"{profile}:private_key_b64", private_key_b64)

    def delete_crypto_credentials(self, profile: str) -> None:
        self._delete(CRYPTO_SERVICE, f"{profile}:api_key")
        self._delete(CRYPTO_SERVICE, f"{profile}:private_key_b64")


class AuthManager:
    def __init__(self, profile: str, session_dir: Path, store: CredentialStore | None = None) -> None:
        self.profile = profile
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._secure_dir(self.session_dir)
        self.store = store or CredentialStore()

    @property
    def session_pickle_path(self) -> Path:
        return self.session_dir / f"robinhood_{self.profile}.pickle"

    @property
    def pickle_name(self) -> str:
        return f"_{self.profile}"

    def _interactive(self) -> bool:
        return sys.stdin.isatty()

    def _load_rh(self):
        try:
            import robin_stocks.robinhood as rh

            return rh
        except Exception as exc:  # pragma: no cover
            raise CLIError(
                code=ErrorCode.INTERNAL_ERROR,
                message=f"Failed to import robin_stocks: {exc}",
            ) from exc

    def _secure_dir(self, path: Path) -> None:
        if path.exists() and path.is_symlink():
            raise CLIError(code=ErrorCode.AUTH_REQUIRED, message=f"Refusing symlinked session directory: {path}")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)
        if path.stat().st_uid != os.getuid():
            raise CLIError(code=ErrorCode.AUTH_REQUIRED, message=f"Session directory not owned by current user: {path}")

    def _secure_session_pickle(self, ensure_exists: bool = False) -> None:
        self._secure_dir(self.session_dir)
        p = self.session_pickle_path
        if ensure_exists and not p.exists():
            raise CLIError(code=ErrorCode.AUTH_REQUIRED, message=f"Session pickle missing: {p}")
        if p.exists():
            if p.is_symlink():
                raise CLIError(code=ErrorCode.AUTH_REQUIRED, message=f"Refusing symlinked session pickle: {p}")
            st = p.stat()
            if st.st_uid != os.getuid():
                raise CLIError(code=ErrorCode.AUTH_REQUIRED, message=f"Session pickle not owned by current user: {p}")
            os.chmod(p, 0o600)

    def _resolve_brokerage_credentials(self) -> tuple[str | None, str | None]:
        username = os.getenv("RH_USERNAME")
        password = os.getenv("RH_PASSWORD")

        if username and password:
            return username, password

        stored_user, stored_pass = self.store.get_robinhood_credentials(self.profile)
        return username or stored_user, password or stored_pass

    def ensure_brokerage_authenticated(self, interactive: bool | None = None, force: bool = False) -> AuthStatus:
        use_interactive = self._interactive() if interactive is None else interactive
        return self.login_brokerage(interactive=use_interactive, force=force)

    def login_brokerage(self, interactive: bool = True, force: bool = False) -> AuthStatus:
        rh = self._load_rh()

        self._secure_dir(self.session_dir)
        self._secure_session_pickle(ensure_exists=False)

        if force and self.session_pickle_path.exists():
            self.session_pickle_path.unlink(missing_ok=True)

        username, password = self._resolve_brokerage_credentials()
        has_cached_session = self.session_pickle_path.exists()

        if (not username or not password) and not interactive and not has_cached_session:
            raise CLIError(
                code=ErrorCode.AUTH_REQUIRED,
                message="Missing Robinhood username/password for non-interactive login",
            )

        if not username and interactive:
            username = input("Robinhood username: ").strip()
        if not password and interactive:
            password = getpass.getpass("Robinhood password: ").strip()

        if (not username or not password) and not has_cached_session:
            raise CLIError(code=ErrorCode.AUTH_REQUIRED, message="Robinhood credentials are required")

        mfa_code = os.getenv("RH_MFA_CODE")
        try:
            data = rh.login(
                username=username,
                password=password,
                store_session=True,
                mfa_code=mfa_code,
                pickle_path=str(self.session_dir),
                pickle_name=self.pickle_name,
            )
        except Exception as exc:
            msg = str(exc)
            lower = msg.lower()
            if any(k in lower for k in ("mfa", "challenge", "verification")):
                raise CLIError(code=ErrorCode.MFA_REQUIRED, message=msg) from exc
            raise CLIError(code=ErrorCode.AUTH_REQUIRED, message=msg) from exc

        if not isinstance(data, dict):
            raise CLIError(code=ErrorCode.AUTH_REQUIRED, message="Brokerage authentication failed")

        if data.get("access_token") or "detail" in data:
            try:
                self.store.set_robinhood_credentials(self.profile, username, password)
            except Exception as exc:
                # Credentials remain available through env vars.
                logger.warning("Failed to persist Robinhood credentials in keyring: %s", exc)

            self._secure_session_pickle(ensure_exists=False)

            return AuthStatus(
                provider="brokerage",
                authenticated=True,
                detail=data.get("detail") or "Authenticated",
            )

        if any(k in data for k in ("verification_workflow", "mfa_required")):
            raise CLIError(
                code=ErrorCode.MFA_REQUIRED,
                message="MFA challenge required",
            )

        raise CLIError(code=ErrorCode.AUTH_REQUIRED, message=f"Login failed: {data}")

    def brokerage_status(self) -> AuthStatus:
        try:
            status = self.ensure_brokerage_authenticated(interactive=False, force=False)
            return status
        except CLIError as exc:
            if exc.code == ErrorCode.MFA_REQUIRED:
                return AuthStatus(
                    provider="brokerage",
                    authenticated=False,
                    mfa_required=True,
                    detail=exc.message,
                )
            return AuthStatus(
                provider="brokerage",
                authenticated=False,
                mfa_required=False,
                detail=exc.message,
            )

    def refresh_brokerage(self, interactive: bool = True) -> AuthStatus:
        return self.ensure_brokerage_authenticated(interactive=interactive, force=True)

    def logout_brokerage(self, forget_creds: bool = False) -> None:
        try:
            rh = self._load_rh()
            rh.logout()
        except Exception as exc:
            logger.warning("Brokerage logout call failed: %s", exc)

        self._secure_session_pickle(ensure_exists=False)
        self.session_pickle_path.unlink(missing_ok=True)

        if forget_creds:
            self.store.delete_robinhood_credentials(self.profile)

    def crypto_credentials(self) -> tuple[str | None, str | None]:
        env_api = os.getenv("RH_CRYPTO_API_KEY")
        env_key = os.getenv("RH_CRYPTO_PRIVATE_KEY_B64")
        if env_api and env_key:
            return env_api, env_key

        stored_api, stored_key = self.store.get_crypto_credentials(self.profile)
        return env_api or stored_api, env_key or stored_key

    def crypto_status(self) -> AuthStatus:
        api_key, private_key = self.crypto_credentials()
        ok = bool(api_key and private_key)
        return AuthStatus(
            provider="crypto",
            authenticated=ok,
            detail="Credentials configured" if ok else "Missing RH_CRYPTO_API_KEY or RH_CRYPTO_PRIVATE_KEY_B64",
        )
