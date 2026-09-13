"""Configuration validation tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from lgtv_controller.config import DEFAULT_TV_CERT_SHA256, AppConfig


def test_configuration_normalizes_network_identifiers(tmp_path: Path) -> None:
    config = AppConfig.create(
        tv_host="192.168.0.1",
        certificate_sha256=":".join(
            DEFAULT_TV_CERT_SHA256[index : index + 2] for index in range(0, len(DEFAULT_TV_CERT_SHA256), 2)
        ),
        tv_mac="aa-bb-cc-dd-ee-ff",
        broadcast_address="192.168.0.255",
        state_dir=tmp_path,
    )

    assert config.tv_host == "192.168.0.1"
    assert config.tv_mac == "AA:BB:CC:DD:EE:FF"
    assert config.certificate_digest.hex() == DEFAULT_TV_CERT_SHA256


@pytest.mark.parametrize("host", ["tv.local", "2001:db8::1", "not-an-address"])
def test_configuration_rejects_non_ipv4_hosts(tmp_path: Path, host: str) -> None:
    with pytest.raises(ValueError, match="IPv4 address literal"):
        AppConfig.create(tv_host=host, state_dir=tmp_path)


def test_configuration_rejects_bad_certificate_fingerprint(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        AppConfig.create(certificate_sha256="00:11", state_dir=tmp_path)


def test_configuration_rejects_relative_state_directory() -> None:
    with pytest.raises(ValueError, match="absolute path"):
        AppConfig.create(state_dir=Path("state"))
