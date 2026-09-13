"""Validated application configuration."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path

DEFAULT_TV_HOST = "192.168.0.1"
DEFAULT_TV_CERT_SHA256 = "00" * 32
DEFAULT_TV_MAC = "AA:BB:CC:DD:EE:FF"
DEFAULT_BROADCAST = "192.168.0.255"

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}", re.ASCII)
_MAC_PATTERN = re.compile(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", re.ASCII)
_IPV4_VERSION = 4


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Immutable settings for one explicitly configured TV."""

    tv_host: str
    certificate_sha256: str
    tv_mac: str
    broadcast_address: str
    state_dir: Path

    @property
    def certificate_digest(self) -> bytes:
        """Return the configured SHA-256 certificate digest as bytes."""
        return bytes.fromhex(self.certificate_sha256)

    @classmethod
    def from_environment(cls) -> AppConfig:
        """Load configuration from the process environment."""
        state_dir = Path(
            os.environ.get(
                "LGTV_STATE_DIR",
                Path.home() / ".config" / "lgtv-controller",
            )
        ).expanduser()
        return cls.create(
            tv_host=os.environ.get("LGTV_HOST", DEFAULT_TV_HOST),
            certificate_sha256=os.environ.get("LGTV_CERT_SHA256", DEFAULT_TV_CERT_SHA256),
            tv_mac=os.environ.get("LGTV_MAC", DEFAULT_TV_MAC),
            broadcast_address=os.environ.get("LGTV_BROADCAST", DEFAULT_BROADCAST),
            state_dir=state_dir,
        )

    @classmethod
    def create(
        cls,
        *,
        tv_host: str = DEFAULT_TV_HOST,
        certificate_sha256: str = DEFAULT_TV_CERT_SHA256,
        tv_mac: str = DEFAULT_TV_MAC,
        broadcast_address: str = DEFAULT_BROADCAST,
        state_dir: Path,
    ) -> AppConfig:
        """Validate explicit configuration values."""
        host = _ipv4_literal(tv_host, "LGTV_HOST")
        broadcast = _ipv4_literal(broadcast_address, "LGTV_BROADCAST")
        fingerprint = certificate_sha256.replace(":", "").lower()
        if _SHA256_PATTERN.fullmatch(fingerprint) is None:
            msg = "LGTV_CERT_SHA256 must be a 64-character SHA-256 fingerprint."
            raise ValueError(msg)

        mac = tv_mac.upper().replace("-", ":")
        if _MAC_PATTERN.fullmatch(mac) is None:
            msg = "LGTV_MAC must contain six hexadecimal octets."
            raise ValueError(msg)

        if not state_dir.is_absolute():
            msg = "LGTV_STATE_DIR must be an absolute path."
            raise ValueError(msg)

        return cls(
            tv_host=host,
            certificate_sha256=fingerprint,
            tv_mac=mac,
            broadcast_address=broadcast,
            state_dir=state_dir.resolve(strict=False),
        )


def _ipv4_literal(value: str, setting_name: str) -> str:
    try:
        parsed = ip_address(value)
    except ValueError as error:
        msg = f"{setting_name} must be an IPv4 address literal."
        raise ValueError(msg) from error
    if parsed.version != _IPV4_VERSION:
        msg = f"{setting_name} must be an IPv4 address literal."
        raise ValueError(msg)
    return str(parsed)
