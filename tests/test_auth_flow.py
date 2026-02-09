from __future__ import annotations

from pathlib import Path

import pytest

from rhx.auth import AuthManager
from rhx.errors import CLIError, ErrorCode


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
    def __init__(self, response=None, exc: Exception | None = None) -> None:
        self.response = response if response is not None else {"access_token": "tok", "token_type": "Bearer"}
        self.exc = exc
        self.calls = 0

    def login(self, **kwargs):
        del kwargs
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.response

    def logout(self):
        return None


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    d = tmp_path / "sessions"
    d.mkdir(parents=True)
    return d


def test_first_login_stores_credentials(monkeypatch: pytest.MonkeyPatch, session_dir: Path) -> None:
    store = InMemoryStore()
    auth = AuthManager(profile="default", session_dir=session_dir, store=store)

    monkeypatch.setenv("RH_USERNAME", "alice")
    monkeypatch.setenv("RH_PASSWORD", "super-secret")

    fake = FakeRH()
    monkeypatch.setattr(auth, "_load_rh", lambda: fake)

    status = auth.login_brokerage(interactive=False)

    assert status.authenticated is True
    assert store.data["default:username"] == "alice"
    assert store.data["default:password"] == "super-secret"
    assert fake.calls == 1


def test_noninteractive_missing_credentials_errors(session_dir: Path) -> None:
    store = InMemoryStore()
    auth = AuthManager(profile="default", session_dir=session_dir, store=store)

    with pytest.raises(CLIError) as exc:
        auth.login_brokerage(interactive=False)

    assert exc.value.code == ErrorCode.AUTH_REQUIRED


def test_noninteractive_uses_cached_session(monkeypatch: pytest.MonkeyPatch, session_dir: Path) -> None:
    store = InMemoryStore()
    auth = AuthManager(profile="default", session_dir=session_dir, store=store)
    auth.session_pickle_path.write_bytes(b"cached")

    fake = FakeRH(response={"detail": "logged in using authentication"})
    monkeypatch.setattr(auth, "_load_rh", lambda: fake)

    status = auth.login_brokerage(interactive=False)

    assert status.authenticated is True
    assert fake.calls == 1


def test_mfa_required_maps_to_error(monkeypatch: pytest.MonkeyPatch, session_dir: Path) -> None:
    store = InMemoryStore()
    store.set_robinhood_credentials("default", "alice", "pw")
    auth = AuthManager(profile="default", session_dir=session_dir, store=store)

    fake = FakeRH(exc=RuntimeError("MFA challenge required"))
    monkeypatch.setattr(auth, "_load_rh", lambda: fake)

    with pytest.raises(CLIError) as exc:
        auth.login_brokerage(interactive=False)

    assert exc.value.code == ErrorCode.MFA_REQUIRED
