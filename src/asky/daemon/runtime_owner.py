"""Daemon runtime ownership and mutual exclusion helpers."""

from __future__ import annotations

import json
import logging
import os
import signal
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DAEMON_LOCK_PATH = Path.home() / ".config" / "asky" / "locks" / "daemon.lock"


class RuntimeMode(Enum):
    TRAY = "tray"
    HEADLESS = "headless"


@dataclass
class RuntimeOwnerMetadata:
    pid: int
    mode: str  # "tray" or "headless"
    start_time: float


class RuntimeOwnerLock:
    """File-lock that tracks daemon ownership and allows mode-based takeovers."""

    def __init__(self, lock_path: Path = DAEMON_LOCK_PATH):
        self._lock_path = Path(lock_path).expanduser()
        self._handle = None

    def is_conflict(self, requested_mode: RuntimeMode) -> bool:
        """Return True if an existing owner conflicts with the requested mode.
        
        A conflict exists if an alive process owns the lock and it's not a 
        supported takeover case (like Tray taking over Headless).
        """
        owner = self.get_owner()
        if not owner or not self._is_process_alive(owner.pid):
            return False
            
        if requested_mode == RuntimeMode.TRAY and owner.mode == RuntimeMode.HEADLESS.value:
            # Takeover allowed
            return False
            
        return True

    def acquire(self, mode: RuntimeMode) -> bool:
        """Acquire the lock, potentially taking over from an existing owner."""
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Try to read existing owner
        existing = self.get_owner()
        if existing:
            if existing.pid == os.getpid():
                return True
                
            if self._is_process_alive(existing.pid):
                if mode == RuntimeMode.TRAY and existing.mode == RuntimeMode.HEADLESS.value:
                    logger.info("Tray runtime requested; taking over from headless owner PID=%s", existing.pid)
                    if not self._takeover(existing.pid):
                        return False
                else:
                    return False
            else:
                logger.debug("Found stale lock file for PID=%s; removing.", existing.pid)
                self._lock_path.unlink(missing_ok=True)

        # Now try to acquire the actual file lock
        try:
            # We use a simple pid file for now as a flock-based implementation
            # would require keeping the handle open.
            metadata = RuntimeOwnerMetadata(
                pid=os.getpid(),
                mode=mode.value,
                start_time=time.time(),
            )
            self._lock_path.write_text(json.dumps(asdict(metadata)))
            return True
        except Exception:
            logger.exception("Failed to write daemon lock file")
            return False

    def release(self) -> None:
        """Release the lock if held by current process."""
        owner = self.get_owner()
        if owner and owner.pid == os.getpid():
            self._lock_path.unlink(missing_ok=True)

    def get_owner(self) -> Optional[RuntimeOwnerMetadata]:
        """Read current owner metadata from the lock file."""
        if not self._lock_path.exists():
            return None
        try:
            data = json.loads(self._lock_path.read_text())
            return RuntimeOwnerMetadata(**data)
        except Exception:
            return None

    def _is_process_alive(self, pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _takeover(self, pid: int) -> bool:
        """Attempt to stop the existing process so we can take over."""
        # Best-effort disable headless startup to avoid conflicts
        try:
            from asky.daemon import startup
            startup.disable_startup()
        except Exception:
            logger.debug("failed to disable headless startup during takeover", exc_info=True)

        # On Linux/macOS we can send SIGTERM
        if os.name == "nt":
            # Windows takeover - might need different approach, but for now try to terminate
            import subprocess
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        else:
            try:
                os.kill(pid, signal.SIGTERM)
                # Wait a bit for it to exit
                for _ in range(10):
                    time.sleep(0.1)
                    if not self._is_process_alive(pid):
                        return True
                # If still alive, try SIGKILL
                os.kill(pid, signal.SIGKILL)
                time.sleep(0.1)
                return not self._is_process_alive(pid)
            except OSError:
                return True
        return not self._is_process_alive(pid)
