"""Background work the browser asked for, and how to ask it how that is going.

A `fray fetch` takes a second and a `fray simulate --runs 50` takes minutes, so
a POST cannot answer with a result: it answers with a job id, the work happens
on a thread, and the browser polls. One shape for all three actions, even
though two of them would have fitted in a request, because two shapes is one
more than anybody wants to learn.

**This is the only mutable state in the GUI, and it is deliberately here.**
`worldmap.py` stays pure and `server.py` stays a router; the registry that
grows and mutates lives in its own module, so the rule that the pure layer
carries no module-level mutable state - the one `simulate --jobs` depends on -
is not eroded by proximity.

**One worker thread per job, and no pool.** These are minutes-long,
user-initiated and few; a pool would add a queue, a size to tune and a
shutdown path to get wrong, in exchange for bounding something that is already
bounded by how fast a person can click. `daemon=True`, so Ctrl-C is not held
hostage by a running simulation - the run is abandoned, and because
`batch.run_batch` claims its directory with `mkdir(exist_ok=False)` and writes
each run atomically, an abandoned batch leaves a partial directory rather than
a corrupt one.
"""

from __future__ import annotations

import threading
import traceback
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class JobState(StrEnum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    """One unit of work, mutated by its own thread and read by requests.

    Every field is written by the worker and read by `handle_request` on some
    other thread. Python's GIL makes each of those assignments atomic, and
    nothing here needs two fields to change together - a reader that catches
    `progress` a moment stale is showing a progress line a moment stale, which
    is what a progress line is.
    """

    id: str
    action: str
    state: JobState = JobState.RUNNING
    progress: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action,
            "state": str(self.state),
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


#: What a job's work function is handed to report progress with. A plain
#: callable rather than a queue: the browser polls, so there is nothing to
#: deliver to and nowhere for a backlog to build up.
Progress = Callable[[str], None]

#: The work itself. Returns whatever the browser should see on success.
Work = Callable[[Progress], dict[str, Any]]


class JobRegistry:
    """Every job this server has run, newest last.

    Bounded by `limit`, because a session that simulates all afternoon should
    not grow a list nobody reads. Finished jobs are dropped oldest-first;
    running ones are never dropped, since something is still holding their id.
    """

    def __init__(self, limit: int = 50) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}
        self._limit = limit

    def submit(self, action: str, work: Work) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], action=action)
        with self._lock:
            self._jobs[job.id] = job
            self._trim()

        def run() -> None:
            try:
                job.result = work(lambda message: setattr(job, "progress", message))
                job.state = JobState.DONE
            except Exception as exc:  # noqa: BLE001 - the browser gets the message
                # The traceback goes to the terminal because it names paths on
                # this machine; the browser gets the one-line reason.
                traceback.print_exc()
                job.error = f"{type(exc).__name__}: {exc}"
                job.state = JobState.FAILED
            finally:
                job.finished_at = datetime.now(UTC).isoformat()

        threading.Thread(target=run, name=f"fray-gui-{action}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    def _trim(self) -> None:
        """Drop the oldest finished jobs. Callers hold `_lock`."""
        if len(self._jobs) <= self._limit:
            return
        finished = [job for job in self._jobs.values() if job.state is not JobState.RUNNING]
        for job in finished[: len(self._jobs) - self._limit]:
            del self._jobs[job.id]


def as_int(payload: Mapping[str, Any], name: str, default: int) -> int:
    """One JSON field as a positive int, or its default.

    JSON gives no integer type distinct from float, and a browser sending
    `"3"` from an input box is the normal case rather than an error, so this
    coerces rather than rejecting. A value that cannot be a count at all -
    zero, negative, unparseable - falls back, because the alternative is a
    simulation of -1 rolls.
    """
    raw = payload.get(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


__all__ = ["Job", "JobRegistry", "JobState", "Progress", "Work", "as_int"]
