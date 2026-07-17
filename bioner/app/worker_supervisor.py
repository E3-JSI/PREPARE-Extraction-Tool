import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 10.0


def _zombie_child_pids(proc_root: Path = Path("/proc")) -> set[int]:
    """PIDs of direct children in zombie state (empty where /proc is absent)."""
    me = os.getpid()
    zombies: set[int] = set()
    if not proc_root.is_dir():
        return zombies
    for entry in proc_root.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text()
            # The comm field may contain spaces or parens; state and ppid are
            # the first two fields after the last ")".
            state, ppid = stat.rsplit(")", 1)[1].split()[:2]
        except (OSError, ValueError, IndexError):
            continue
        if state == "Z" and int(ppid) == me:
            zombies.add(int(entry.name))
    return zombies


def start_worker_supervisor(
    interval: float = CHECK_INTERVAL_SECONDS,
) -> threading.Thread:
    """Start the daemon thread that exits the service on worker death.

    A PID must be a zombie on two consecutive scans before acting, so a
    child mid-reap during a legitimate shutdown never triggers an exit.
    """

    def _watch():
        previous: set[int] = set()
        while True:
            time.sleep(interval)
            zombies = _zombie_child_pids()
            confirmed = zombies & previous
            if confirmed:
                logger.error(
                    "Worker process(es) %s died (likely killed by the OS, e.g. "
                    "out of memory) — exiting so the container restarts cleanly.",
                    sorted(confirmed),
                )
                os._exit(1)
            previous = zombies

    thread = threading.Thread(target=_watch, daemon=True, name="worker-supervisor")
    thread.start()
    return thread
