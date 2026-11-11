"""Is the reader process alive? The container's health check.

The reader touches ``ALIVE_FILE`` on every pass of its loop, while it waits for work, and
every second while it reads a document. A file that has not been touched for ``MAX_AGE_SECONDS``
means the process is hung (or gone), and the container is marked unhealthy.

Run as ``python -m backend.app.workers.reader_health``: exit code 0 when alive, 1 when not.
Standard library only, so the check starts fast and cannot fail on a missing setting.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ALIVE_FILE = Path(os.environ.get("S1_READER_ALIVE_FILE", "/tmp/s1-reader-alive"))
MAX_AGE_SECONDS = 90


def is_alive(path: Path = ALIVE_FILE, now: float | None = None, max_age: float = MAX_AGE_SECONDS) -> bool:
    """True when ``path`` was modified within ``max_age`` seconds of ``now``. A missing file is not alive."""

    try:
        modified = path.stat().st_mtime
    except OSError:
        return False
    return (time.time() if now is None else now) - modified <= max_age


def main() -> int:
    return 0 if is_alive(ALIVE_FILE) else 1  # ALIVE_FILE is read here, not bound at import


if __name__ == "__main__":
    sys.exit(main())
