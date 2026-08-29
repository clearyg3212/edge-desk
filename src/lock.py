"""Exclusive lock around load → evaluate → settle → fill → save."""
from __future__ import annotations

import os
import time
from pathlib import Path


class DataLock:
    def __init__(self, path: Path, timeout: float = 30.0):
        self.path = path
        self.timeout = timeout
        self.fp = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fp = open(self.path, "a+b")
        start = time.time()
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    self.fp.seek(0)
                    msvcrt.locking(self.fp.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except (OSError, BlockingIOError):
                if time.time() - start > self.timeout:
                    raise RuntimeError("paper blotter is locked — another scan is running")
                time.sleep(0.2)

    def __exit__(self, *exc):
        if not self.fp:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self.fp.seek(0)
                msvcrt.locking(self.fp.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fp.fileno(), fcntl.LOCK_UN)
        finally:
            self.fp.close()
            self.fp = None
