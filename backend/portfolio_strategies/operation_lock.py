from __future__ import annotations

from contextlib import contextmanager
import fcntl
from pathlib import Path
import re
import time
from collections.abc import Iterator


class PortfolioOperationLockedError(RuntimeError):
    pass


def _safe_name(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", value)


@contextmanager
def portfolio_operation_lock(
    db_path: Path | str,
    name: str,
    *,
    timeout_seconds: float = 0.0,
) -> Iterator[None]:
    """Serialize account mutations across workers and scheduled processes."""
    root = Path(db_path).parent / ".portfolio-locks"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{_safe_name(name)}.lock"
    handle = path.open("a+", encoding="utf-8")
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    try:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise PortfolioOperationLockedError(
                        f"Portfolio operation already running: {name}"
                    )
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
