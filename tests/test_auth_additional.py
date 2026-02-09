from __future__ import annotations

from pathlib import Path

import pytest
from keyring.errors import KeyringError

import rhx.auth as auth_module
from rhx.auth import AuthManager, CredentialStore
from rhx.errors import CLIError, ErrorCode


class InMemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.deleted_crypto = False

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
        self.deleted_crypto = True
        self.data.pop(f"{profile}:api_key", None)
        self.data.pop(f"{profile}:private_key_b64", None)


class FakeRH:
    def __init__(self, response=None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc
        self.logged_out = False

    def login(self, **kwargs):
        del kwargs
        if self.exc:
            raise self.exc
        return self.response

    def logout(self):
        self.logged_out = True


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir(parents=True)
    return d


def test_credential_store_handles_keyring_errors(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(auth_module.keyring, "get_password", lambda *args, **kwargs: (_ for _ in ()).throw(KeyringError()))
    monkeypatch.setattr(auth_module.keyring, "set_password", lambda *args, **kwargs: None)
    monkeypatch.setattr(auth_module.keyring, "delete_password", lambda *args, **kwargs: (_ for _ in ()).throw(KeyringError()))

    store = CredentialStore()
    assert store.get_robinhood_credentials("default") == (None, None)
    store.set_robinhood_credentials("default", "u", "p")
    store.delete_robinhood_credentials("default")


def test_login_non_dict_response_errors(monkeypatch: pytest.MonkeyPatch, session_dir: Path):
    auth = AuthManager(profile="default", session_dir=session_dir, store=InMemoryStore())
    monkeypatch.setenv("RH_USERNAME", "alice")
    monkeypatch.setenv("RH_PASSWORD", "pw")
    monkeypatch.setattr(auth, "_load_rh", lambda: FakeRH(response="not-a-dict"))
    monkeypatch.setattr(auth, "_login_brokerage_fallback", lambda *args, **kwargs: pytest.fail("unexpected fallback"))

    with pytest.raises(CLIError) as exc:
        auth.login_brokerage(interactive=False)
    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_login_dict_mfa_required_errors(monkeypatch: pytest.MonkeyPatch, session_dir: Path):
    auth = AuthManager(profile="default", session_dir=session_dir, store=InMemoryStore())
    monkeypatch.setenv("RH_USERNAME", "alice")
    monkeypatch.setenv("RH_PASSWORD", "pw")
    monkeypatch.setattr(auth, "_load_rh", lambda: FakeRH(response={"verification_workflow": {"id": "x"}}))

    with pytest.raises(CLIError) as exc:
        auth.login_brokerage(interactive=False)
    assert exc.value.code == ErrorCode.MFA_REQUIRED


def test_login_none_response_uses_fallback(monkeypatch: pytest.MonkeyPatch, session_dir: Path):
    store = InMemoryStore()
    auth = AuthManager(profile="default", session_dir=session_dir, store=store)
    monkeypatch.setenv("RH_USERNAME", "alice")
    monkeypatch.setenv("RH_PASSWORD", "pw")
    fake = FakeRH(response=None)
    monkeypatch.setattr(auth, "_load_rh", lambda: fake)

    calls: dict[str, str] = {}

    def fake_fallback(rh, username: str, password: str, mfa_code: str | None):
        calls["username"] = username
        calls["password"] = password
        calls["mfa_code"] = mfa_code or ""
        assert rh is fake
        return {"access_token": "tok", "detail": "Authenticated via fallback"}

    monkeypatch.setattr(auth, "_login_brokerage_fallback", fake_fallback)

    status = auth.login_brokerage(interactive=False)

    assert status.authenticated is True
    assert "fallback" in status.detail.lower()
    assert calls["username"] == "alice"
    assert calls["password"] == "pw"


def test_brokerage_status_mfa_flag(monkeypatch: pytest.MonkeyPatch, session_dir: Path):
    auth = AuthManager(profile="default", session_dir=session_dir, store=InMemoryStore())

    def fail(*args, **kwargs):
        del args, kwargs
        raise CLIError(code=ErrorCode.MFA_REQUIRED, message="challenge")

    monkeypatch.setattr(auth, "ensure_brokerage_authenticated", fail)
    status = auth.brokerage_status()
    assert status.authenticated is False
    assert status.mfa_required is True


def test_logout_forget_creds(monkeypatch: pytest.MonkeyPatch, session_dir: Path):
    store = InMemoryStore()
    auth = AuthManager(profile="default", session_dir=session_dir, store=store)
    auth.session_pickle_path.write_text("cached")
    fake_rh = FakeRH(response={"access_token": "tok"})
    monkeypatch.setattr(auth, "_load_rh", lambda: fake_rh)

    auth.logout_brokerage(forget_creds=True)

    assert fake_rh.logged_out is True
    assert not auth.session_pickle_path.exists()


def test_crypto_credentials_env_precedence(monkeypatch: pytest.MonkeyPatch, session_dir: Path):
    store = InMemoryStore()
    store.set_crypto_credentials("default", "stored_key", "stored_secret")
    auth = AuthManager(profile="default", session_dir=session_dir, store=store)

    monkeypatch.setenv("RH_CRYPTO_API_KEY", "env_key")
    monkeypatch.setenv("RH_CRYPTO_PRIVATE_KEY_B64", "env_secret")

    api_key, secret = auth.crypto_credentials()
    assert api_key == "env_key"
    assert secret == "env_secret"


def test_login_rejects_symlinked_session_pickle(monkeypatch: pytest.MonkeyPatch, session_dir: Path):
    auth = AuthManager(profile="default", session_dir=session_dir, store=InMemoryStore())
    monkeypatch.setenv("RH_USERNAME", "alice")
    monkeypatch.setenv("RH_PASSWORD", "pw")
    monkeypatch.setattr(auth, "_load_rh", lambda: FakeRH(response={"access_token": "tok"}))

    target = session_dir / "real.pickle"
    target.write_text("session")
    auth.session_pickle_path.symlink_to(target)

    with pytest.raises(CLIError) as exc:
        auth.login_brokerage(interactive=False)
    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_logout_rejects_symlinked_session_pickle(monkeypatch: pytest.MonkeyPatch, session_dir: Path):
    auth = AuthManager(profile="default", session_dir=session_dir, store=InMemoryStore())
    monkeypatch.setattr(auth, "_load_rh", lambda: FakeRH(response={"access_token": "tok"}))

    target = session_dir / "real.pickle"
    target.write_text("session")
    auth.session_pickle_path.symlink_to(target)

    with pytest.raises(CLIError) as exc:
        auth.logout_brokerage(forget_creds=False)
    assert exc.value.code == ErrorCode.AUTH_REQUIRED
