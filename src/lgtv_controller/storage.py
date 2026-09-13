"""Private, atomic storage for application secrets and pairing state."""

from __future__ import annotations

import json
import os
import secrets
import stat
import tempfile
from pathlib import Path
from typing import Final

_MAX_STATE_BYTES: Final = 4_096
_CLIENT_STATE_VERSION: Final = 1
_MIN_SECRET_LENGTH: Final = 32
_MIN_CLIENT_KEY_LENGTH: Final = 16
_MAX_CLIENT_KEY_LENGTH: Final = 256


class StateFileError(RuntimeError):
    """Raised when persisted state is unsafe or invalid."""


class StateStore:
    """Store local secrets in an owner-only directory."""

    def __init__(self, directory: Path, *, tv_host: str, certificate_sha256: str) -> None:
        """Configure state paths for one certificate-bound TV."""
        self.directory = directory
        self.tv_host = tv_host
        self.certificate_sha256 = certificate_sha256
        self._secret_path = directory / "web-secret"
        self._client_path = directory / "client.json"

    def load_or_create_web_secret(self) -> str:
        """Return a stable application signing secret."""
        self._ensure_directory()
        if self._secret_path.exists():
            secret = self._read_private(self._secret_path).decode("ascii")
            if len(secret) < _MIN_SECRET_LENGTH:
                msg = "Stored web secret is too short."
                raise StateFileError(msg)
            return secret

        secret = secrets.token_urlsafe(48)
        self._write_private(self._secret_path, secret.encode("ascii"))
        return secret

    def load_client_key(self) -> str | None:
        """Load a pairing key bound to the configured host and certificate."""
        self._ensure_directory()
        if not self._client_path.exists():
            return None
        try:
            data = json.loads(self._read_private(self._client_path))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            msg = "Stored TV pairing state is invalid."
            raise StateFileError(msg) from error

        expected = {
            "version": _CLIENT_STATE_VERSION,
            "tv_host": self.tv_host,
            "certificate_sha256": self.certificate_sha256,
        }
        if not isinstance(data, dict) or any(data.get(key) != value for key, value in expected.items()):
            msg = "Stored pairing state does not match the configured TV."
            raise StateFileError(msg)

        client_key = data.get("client_key")
        if (
            not isinstance(client_key, str)
            or not _MIN_CLIENT_KEY_LENGTH <= len(client_key) <= _MAX_CLIENT_KEY_LENGTH
            or not client_key.isascii()
        ):
            msg = "Stored TV client key is invalid."
            raise StateFileError(msg)
        return client_key

    def save_client_key(self, client_key: str) -> None:
        """Persist a newly approved TV client key."""
        if not _MIN_CLIENT_KEY_LENGTH <= len(client_key) <= _MAX_CLIENT_KEY_LENGTH or not client_key.isascii():
            msg = "TV returned an invalid client key."
            raise StateFileError(msg)
        payload = {
            "version": _CLIENT_STATE_VERSION,
            "tv_host": self.tv_host,
            "certificate_sha256": self.certificate_sha256,
            "client_key": client_key,
        }
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self._ensure_directory()
        self._write_private(self._client_path, encoded)

    def forget_client_key(self) -> None:
        """Remove the locally persisted pairing key."""
        self._client_path.unlink(missing_ok=True)

    def _ensure_directory(self) -> None:
        if self.directory.is_symlink():
            msg = "State directory must not be a symbolic link."
            raise StateFileError(msg)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)

    @staticmethod
    def _read_private(path: Path) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as error:
            msg = f"Unable to open private state file: {path.name}."
            raise StateFileError(msg) from error
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
                msg = f"Private state file has unsafe ownership or type: {path.name}."
                raise StateFileError(msg)
            if stat.S_IMODE(metadata.st_mode) & 0o077:
                msg = f"Private state file permissions are too broad: {path.name}."
                raise StateFileError(msg)
            if metadata.st_size > _MAX_STATE_BYTES:
                msg = f"Private state file is unexpectedly large: {path.name}."
                raise StateFileError(msg)
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                return stream.read(_MAX_STATE_BYTES + 1)
        finally:
            os.close(descriptor)

    def _write_private(self, path: Path, payload: bytes) -> None:
        if len(payload) > _MAX_STATE_BYTES:
            msg = "Refusing to persist oversized state."
            raise StateFileError(msg)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=self.directory)
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temporary_path.replace(path)
            directory_descriptor = os.open(self.directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        finally:
            os.close(descriptor)
            temporary_path.unlink(missing_ok=True)
