from __future__ import annotations

import getpass
from pathlib import Path

import pytest

import rhx.auth as auth_module
from rhx.auth import AuthManager, CredentialStore
from rhx.errors import CLIError, ErrorCode
from rhx.models import AuthStatus


class InMemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get_robinhood_credentials(self, profile: str):
        return self.data.get(f"{profile}:username"), self.data.get(f"{profile}:password")

    def set_robinhood_credentials(self, profile: str, username: str, password: str):
        self.data[f"{profile}:username"] = username
        self.data[f"{profile}:password"] = password

    def delete_robinhood_credentials(self, profile: str):
        self.data.pop(f"{profile}:username", None)
        self.data.pop(f"{profile}:password", None)

    def get_crypto_credentials(self, profile: str):
        return self.data.get(f"{profile}:api_key"), self.data.get(f"{profile}:private_key_b64")

    def set_crypto_credentials(self, profile: str, api_key: str, private_key_b64: str):
        self.data[f"{profile}:api_key"] = api_key
        self.data[f"{profile}:private_key_b64"] = private_key_b64

    def delete_crypto_credentials(self, profile: str):
        self.data.pop(f"{profile}:api_key", None)
        self.data.pop(f"{profile}:private_key_b64", None)


class FakeRH:
    def __init__(self, response=None, exc: Exception | None = None, logout_exc: Exception | None = None):
        self.response = response if response is not None else {"access_token": "tok"}
        self.exc = exc
        self.logout_exc = logout_exc
        self.calls = 0

    def login(self, **kwargs):
        del kwargs
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.response

    def logout(self):
        if self.logout_exc:
            raise self.logout_exc


def test_credential_store_success_paths(monkeypatch: pytest.MonkeyPatch):
    values: dict[tuple[str, str], str] = {}

    def fake_get(service: str, key: str):
        return values.get((service, key))

    def fake_set(service: str, key: str, value: str):
        values[(service, key)] = value

    def fake_delete(service: str, key: str):
        values.pop((service, key), None)

    monkeypatch.setattr(auth_module.keyring, "get_password", fake_get)
    monkeypatch.setattr(auth_module.keyring, "set_password", fake_set)
    monkeypatch.setattr(auth_module.keyring, "delete_password", fake_delete)

    store = CredentialStore()
    store.set_robinhood_credentials("default", "alice", "pw")
    assert store.get_robinhood_credentials("default") == ("alice", "pw")
    store.delete_robinhood_credentials("default")
    assert store.get_robinhood_credentials("default") == (None, None)

    store.set_crypto_credentials("default", "api", "secret")
    assert store.get_crypto_credentials("default") == ("api", "secret")
    store.delete_crypto_credentials("default")
    assert store.get_crypto_credentials("default") == (None, None)


def test_secure_dir_owner_mismatch_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    auth = AuthManager(profile="default", session_dir=tmp_path / "sessions", store=InMemoryStore())

    owner = auth.session_dir.stat().st_uid
    monkeypatch.setattr(auth_module.os, "getuid", lambda: owner + 1)

    with pytest.raises(CLIError) as exc:
        auth._secure_dir(auth.session_dir)
    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_secure_session_pickle_owner_mismatch_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    auth = AuthManager(profile="default", session_dir=tmp_path / "sessions", store=InMemoryStore())
    auth.session_pickle_path.write_text("session")
    owner = auth.session_pickle_path.stat().st_uid

    monkeypatch.setattr(auth, "_secure_dir", lambda path: None)
    monkeypatch.setattr(auth_module.os, "getuid", lambda: owner + 1)

    with pytest.raises(CLIError) as exc:
        auth._secure_session_pickle(ensure_exists=False)
    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_secure_session_pickle_missing_when_required(tmp_path: Path):
    auth = AuthManager(profile="default", session_dir=tmp_path / "sessions", store=InMemoryStore())
    with pytest.raises(CLIError) as exc:
        auth._secure_session_pickle(ensure_exists=True)
    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_login_interactive_prompts_and_force_unlink(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = InMemoryStore()
    auth = AuthManager(profile="default", session_dir=tmp_path / "sessions", store=store)
    auth.session_pickle_path.write_text("stale")
    fake = FakeRH(response={"access_token": "tok"})

    monkeypatch.delenv("RH_USERNAME", raising=False)
    monkeypatch.delenv("RH_PASSWORD", raising=False)
    monkeypatch.setattr(auth, "_load_rh", lambda: fake)
    monkeypatch.setattr("builtins.input", lambda prompt: "alice")
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "pw")

    status = auth.login_brokerage(interactive=True, force=True)

    assert status.authenticated is True
    assert fake.calls == 1
    assert store.data["default:username"] == "alice"
    assert store.data["default:password"] == "pw"


def test_login_interactive_blank_credentials_errors(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    auth = AuthManager(profile="default", session_dir=tmp_path / "sessions", store=InMemoryStore())
    monkeypatch.setattr(auth, "_load_rh", lambda: FakeRH(response={"access_token": "tok"}))
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "")

    with pytest.raises(CLIError) as exc:
        auth.login_brokerage(interactive=True, force=False)
    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_login_exception_maps_auth_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    auth = AuthManager(profile="default", session_dir=tmp_path / "sessions", store=InMemoryStore())
    monkeypatch.setenv("RH_USERNAME", "alice")
    monkeypatch.setenv("RH_PASSWORD", "pw")
    monkeypatch.setattr(auth, "_load_rh", lambda: FakeRH(exc=RuntimeError("boom")))

    with pytest.raises(CLIError) as exc:
        auth.login_brokerage(interactive=False)
    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_login_dict_without_tokens_maps_auth_required(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    auth = AuthManager(profile="default", session_dir=tmp_path / "sessions", store=InMemoryStore())
    monkeypatch.setenv("RH_USERNAME", "alice")
    monkeypatch.setenv("RH_PASSWORD", "pw")
    monkeypatch.setattr(auth, "_load_rh", lambda: FakeRH(response={"foo": "bar"}))

    with pytest.raises(CLIError) as exc:
        auth.login_brokerage(interactive=False)
    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_brokerage_status_success_and_auth_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    auth = AuthManager(profile="default", session_dir=tmp_path / "sessions", store=InMemoryStore())
    ok = AuthStatus(provider="brokerage", authenticated=True, detail="ok")
    monkeypatch.setattr(auth, "ensure_brokerage_authenticated", lambda interactive=False, force=False: ok)

    status_ok = auth.brokerage_status()
    assert status_ok.authenticated is True

    def fail(interactive=False, force=False):
        del interactive, force
        raise CLIError(code=ErrorCode.AUTH_REQUIRED, message="bad")

    monkeypatch.setattr(auth, "ensure_brokerage_authenticated", fail)
    status_bad = auth.brokerage_status()
    assert status_bad.authenticated is False
    assert status_bad.mfa_required is False


def test_refresh_brokerage_forces_login(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    auth = AuthManager(profile="default", session_dir=tmp_path / "sessions", store=InMemoryStore())
    calls: list[tuple[bool, bool]] = []

    def fake_ensure(interactive: bool | None = None, force: bool = False):
        calls.append((bool(interactive), force))
        return AuthStatus(provider="brokerage", authenticated=True, detail="ok")

    monkeypatch.setattr(auth, "ensure_brokerage_authenticated", fake_ensure)

    status = auth.refresh_brokerage(interactive=True)
    assert status.authenticated is True
    assert calls == [(True, True)]


def test_logout_handles_provider_exception(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    auth = AuthManager(profile="default", session_dir=tmp_path / "sessions", store=InMemoryStore())
    auth.session_pickle_path.write_text("session")
    monkeypatch.setattr(auth, "_load_rh", lambda: FakeRH(logout_exc=RuntimeError("logout failed")))

    auth.logout_brokerage(forget_creds=False)
    assert not auth.session_pickle_path.exists()


def test_crypto_credentials_store_fallback_and_status(tmp_path: Path):
    store = InMemoryStore()
    store.set_crypto_credentials("default", "stored_api", "stored_secret")
    auth = AuthManager(profile="default", session_dir=tmp_path / "sessions", store=store)

    api_key, secret = auth.crypto_credentials()
    assert api_key == "stored_api"
    assert secret == "stored_secret"

    empty_auth = AuthManager(profile="default", session_dir=tmp_path / "sessions2", store=InMemoryStore())
    status = empty_auth.crypto_status()
    assert status.authenticated is False
