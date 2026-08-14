"""Background work the browser asked for, and how to ask it how that is going.

A `chunksim fetch` takes a second and a `chunksim simulate --runs 50` takes minutes, so
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
    #: Stopped because somebody asked, which is **not** a failure and must
    #: not be coloured like one. A cancelled simulation keeps every roll it
    #: had finished; see `batch.run_batch`.
    CANCELLED = "cancelled"


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
    #: Set by `JobRegistry.cancel`. The work checks it and stops where it
    #: safely can, so this is a *request* and the job stays `RUNNING` until
    #: the work agrees - which is why the page keeps polling after a cancel
    #: rather than assuming it is over.
    stopping: threading.Event = field(default_factory=threading.Event)

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
            "stopping": self.stopping.is_set(),
        }


#: What a job's work function is handed to report progress with. A plain
#: callable rather than a queue: the browser polls, so there is nothing to
#: deliver to and nowhere for a backlog to build up.
Progress = Callable[[str], None]

#: Asked, once in a while, whether to stop. Work that has nowhere sensible to
#: stop simply never calls it.
StopCheck = Callable[[], bool]

#: The work itself. Returns whatever the browser should see on success.
Work = Callable[[Progress, StopCheck], dict[str, Any]]


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
        self._attempted: set[str] = set()

    def claim_once(self, what: str) -> bool:
        """True the first time this process is asked to do `what`.

        For work the *page* starts rather than the user: the front end warms
        the reference blobs on boot, and without this a reload during a failed
        scrape starts another one. Attempted, not succeeded - a scrape that
        fails should report and stop, not retry itself every time somebody
        opens a tab. An explicit press is a different request and never comes
        through here.
        """
        with self._lock:
            if what in self._attempted:
                return False
            self._attempted.add(what)
            return True

    def submit(self, action: str, work: Work) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], action=action)
        with self._lock:
            self._jobs[job.id] = job
            self._trim()

        def run() -> None:
            try:
                job.result = work(
                    lambda message: setattr(job, "progress", message), job.stopping.is_set
                )
                # **Cancelled, not done.** The work returned normally because
                # it stopped where it was asked to, and a page that coloured
                # that green would be claiming the batch finished.
                job.state = JobState.CANCELLED if job.stopping.is_set() else JobState.DONE
            except Exception as exc:  # noqa: BLE001 - the browser gets the message
                # The traceback goes to the terminal because it names paths on
                # this machine; the browser gets the one-line reason.
                traceback.print_exc()
                job.error = f"{type(exc).__name__}: {exc}"
                job.state = JobState.FAILED
            finally:
                job.finished_at = datetime.now(UTC).isoformat()

        threading.Thread(target=run, name=f"chunksim-gui-{action}", daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> Job | None:
        """Ask a job to stop. Returns it, or `None` if there is no such job.

        **A request, not a kill.** The work decides where it can safely stop -
        `batch.run_batch` finishes the roll it is on - so the job stays
        `RUNNING` until it agrees. Cancelling a finished job is a no-op rather
        than an error: the button and the last poll race, and the user's
        answer to "it had already finished" is nothing.
        """
        with self._lock:
            job = self._jobs.get(job_id)
        if job is not None and job.state is JobState.RUNNING:
            job.stopping.set()
        return job

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
