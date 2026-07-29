"""SHA-256 hashing utilities for pack files and lock files."""

import hashlib
from pathlib import Path


def hash_file(path: Path) -> str:
    """Return SHA-256 hex digest of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_bytes(data: bytes) -> str:
    """Return SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def hash_string(text: str) -> str:
    """Return SHA-256 hex digest of a UTF-8 string."""
    return hash_bytes(text.encode("utf-8"))


def hash_directory(root: Path) -> str:
    """Return a deterministic SHA-256 of all files in a directory tree.

    Files are sorted by relative path to ensure determinism.
    """
    h = hashlib.sha256()
    for file_path in sorted(root.rglob("*")):
        if file_path.is_file():
            rel = file_path.relative_to(root).as_posix()
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            h.update(hash_file(file_path).encode("utf-8"))
            h.update(b"\0")
    return h.hexdigest()


def lock_hash(hex_digest: str) -> str:
    """Format a hex digest as a lock hash string."""
    return f"sha256:{hex_digest}"
