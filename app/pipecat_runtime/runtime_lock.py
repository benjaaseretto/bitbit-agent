"""Prevent duplicate Mac model loads before allocating GPU memory."""
import fcntl
import hashlib
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def single_mac_runtime(root):
    key = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:16]
    path = Path(tempfile.gettempdir()) / f"voice-mlx-{os.getuid()}-{key}.lock"
    with path.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Ya hay un agente Mac ejecutándose para este proyecto.") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
