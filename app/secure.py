"""Recordings encrypted at rest with Fernet (AES-128-CBC + HMAC).

A key lives in `data/recording.key` with unix permissions 600. Encrypted files
start with the `FK1:` marker so reading stays idempotent. Audio playback and
the pipeline fetch plain bytes through small helpers here.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.config import settings

MARKER = b"FK1:"
_KEY_NAME = "recording.key"

try:
    from cryptography.fernet import Fernet, InvalidToken

    ENABLED = True
except ImportError:  # pragma: no cover
    ENABLED = False


def key_path() -> Path:
    """`.env` may point DATA_DIR elsewhere; the key follows the data directory."""
    return Path(settings.DATA_DIR) / _KEY_NAME


def _ensure_key() -> bytes:
    path = key_path()
    if path.is_file() and path.read_bytes():
        return path.read_bytes()
    key = Fernet.generate_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)
    os.chmod(path, 0o600)
    return key


def is_encrypted(path: str | os.PathLike[str]) -> bool:
    """True when `path` holds a protected payload (already locked)."""
    target = Path(path)
    if not target.is_file():
        return False
    with target.open("rb") as stream:
        return stream.read(len(MARKER)) == MARKER


def lock(path: str | os.PathLike[str]) -> None:
    """Encrypt a file in place. Already encrypted files are left alone."""
    if not ENABLED:
        return
    target = Path(path)
    if is_encrypted(target):
        return
    token = Fernet(_ensure_key()).encrypt(target.read_bytes())
    target.write_bytes(MARKER + token)
    os.chmod(target, 0o600)


def plain_bytes(path: str | os.PathLike[str]) -> bytes:
    """Read a recording whether it is encrypted or not."""
    target = Path(path)
    if not ENABLED or not is_encrypted(target):
        return target.read_bytes()
    payload = target.read_bytes()[len(MARKER) :]
    try:
        return Fernet(_ensure_key()).decrypt(payload)
    except InvalidToken as exc:  # pragma: no cover
        raise RuntimeError("нет ключа расшифровки записи") from exc


def unlock_to(path: str | os.PathLike[str], dest: str | os.PathLike[str]) -> Path:
    """Write the plain audio into `dest` and return that Path."""
    target = Path(dest)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(plain_bytes(path))
    return target
