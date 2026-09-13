"""Private state storage tests."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from lgtv_controller.config import DEFAULT_TV_CERT_SHA256
from lgtv_controller.storage import StateFileError, StateStore

TV_HOST = "192.168.0.1"
CLIENT_KEY = "a" * 32


def _store(directory: Path, *, fingerprint: str = DEFAULT_TV_CERT_SHA256) -> StateStore:
    return StateStore(directory, tv_host=TV_HOST, certificate_sha256=fingerprint)


def test_web_secret_is_stable_and_private(tmp_path: Path) -> None:
    store = _store(tmp_path / "state")

    first = store.load_or_create_web_secret()
    second = store.load_or_create_web_secret()

    assert first == second
    assert len(first) >= 32
    assert stat.S_IMODE((store.directory / "web-secret").stat().st_mode) == 0o600
    assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700


def test_client_key_round_trip_is_bound_to_tv_and_certificate(tmp_path: Path) -> None:
    store = _store(tmp_path / "state")
    store.save_client_key(CLIENT_KEY)

    assert store.load_client_key() == CLIENT_KEY
    assert stat.S_IMODE((store.directory / "client.json").stat().st_mode) == 0o600

    other_certificate = _store(store.directory, fingerprint="f" * 64)
    with pytest.raises(StateFileError, match="does not match"):
        other_certificate.load_client_key()


def test_client_state_with_broad_permissions_is_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path / "state")
    store.save_client_key(CLIENT_KEY)
    client_path = store.directory / "client.json"
    client_path.chmod(0o644)

    with pytest.raises(StateFileError, match="permissions are too broad"):
        store.load_client_key()


def test_forget_pairing_removes_only_client_key(tmp_path: Path) -> None:
    store = _store(tmp_path / "state")
    secret = store.load_or_create_web_secret()
    store.save_client_key(CLIENT_KEY)

    store.forget_client_key()

    assert store.load_client_key() is None
    assert store.load_or_create_web_secret() == secret
