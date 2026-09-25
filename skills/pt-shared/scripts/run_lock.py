#!/usr/bin/env python3
"""run_lock.py -- one exclusive run per name, with stale takeover.

The daily paper's run is not idempotent and must not run twice at once.
A manual `openclaw cron run` alongside the scheduled fire would start a
second session; the second finds every section already `running` (the
per-topic guard refuses to duplicate), compiles an empty edition, and
delivers it -- honest in form and misleading in effect, the one job this
agent must never do. The scheduler has no dedup, so the lock is a file
created with O_EXCL: the atomic primitive every process on the host agrees
on.

  acquire --name NAME [--today] [--stale-minutes N] [--wait-seconds N]
  release --name NAME [--today]

`--today` appends `-YYYY-MM-DD`, the owner's day on the owner's clock
(owner_time.py), so a paper's lock is `paper-workspace-2026-09-25` without
the model working out a date: one once wrote last year and the paper never
ran. Pass it to both acquire and release.

`acquire` prints exactly one word and always exits 0, so a cron-fired
session reads the decision instead of a status code:

  acquired        this process owns the run; release it when done
  stale-takeover  a lock was there but older than --stale-minutes, so it is
                  a dead run's leftover, not a live owner; this process now
                  owns it
  held            a fresh owner is running it; stop, do not start a second

`--wait-seconds N` (default 0) makes a fresh `held` wait: acquire polls once
a second -- re-checking staleness each time -- until the lock frees, goes
stale, or N seconds pass, and only then answers `held`. A scheduled paper uses
it so an on-demand copy holding the workspace does not cost it the day.
Keep N under OpenClaw's 30-minute exec timeout: without the
process tool, exec runs synchronously until then.

`release` removes the lock; a missing lock is not an error (the run ended
without acquiring, or two releases raced). The lock directory is
`$PT_HOME/run` -- the same scratch space the notes live in, default
/var/lib/plow/pt.
"""
from __future__ import annotations

import argparse
import fcntl
import os
import pathlib
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from owner_time import owner_today
from pt_paths import pt_home

DEFAULT_STALE_MINUTES = 120
NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def home():
    return pt_home()


def lock_path(name):
    return home() / "run" / f"{name}.lock"


def now():
    return datetime.now(timezone.utc).astimezone()


def age_minutes(text):
    """Minutes since the lock was written; None when it cannot be trusted."""
    try:
        stamp = datetime.fromisoformat(text.strip())
    except (ValueError, AttributeError):
        return None
    if stamp.tzinfo is None:
        return None
    return (now() - stamp).total_seconds() / 60.0


@contextmanager
def guarded(directory):
    """Serialize every check-and-take on this host.

    O_EXCL alone left two windows, both measured with eight simultaneous
    acquirers: a racer could read the lock between its creation and its
    timestamp (empty, so "unparseable", so taken over), and two racers could
    both decide the same stale lock was theirs. Under one flock the lock is
    never seen half-written and only one process ever decides.
    """
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / ".run_lock.guard", "a") as guard:
        fcntl.flock(guard, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(guard, fcntl.LOCK_UN)


def acquire(name, stale_minutes, wait_seconds=0):
    deadline = time.monotonic() + wait_seconds
    while True:
        outcome = _take(name, stale_minutes)
        if outcome != "held" or time.monotonic() >= deadline:
            print(outcome)
            return 0
        time.sleep(1)


def _take(name, stale_minutes):
    """One check-and-take under the host guard: acquired, stale-takeover or held."""
    path = lock_path(name)
    with guarded(path.parent):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                text = path.read_text()
            except OSError:
                text = ""
            age = age_minutes(text)
            if age is None or age > stale_minutes:
                # A lock we cannot parse, or one older than the whole run budget,
                # is a dead run's leftover -- taking it over beats blocking the
                # paper forever. A parsed-and-fresh lock is a live owner: held.
                path.write_text(now().isoformat(timespec="seconds") + "\n")
                return "stale-takeover"
            return "held"
        with os.fdopen(fd, "w") as handle:
            handle.write(now().isoformat(timespec="seconds") + "\n")
    return "acquired"


def release(name):
    path = lock_path(name)
    with guarded(path.parent):
        try:
            path.unlink()
            print("released")
        except FileNotFoundError:
            print("nothing-to-release")
    return 0


def _seconds(raw):
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("--wait-seconds cannot be negative")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    acq = sub.add_parser("acquire", help="take the run lock if free")
    acq.add_argument("--name", required=True)
    acq.add_argument("--today", action="store_true", help="append the owner's date to NAME")
    acq.add_argument("--stale-minutes", type=int, default=DEFAULT_STALE_MINUTES)
    acq.add_argument("--wait-seconds", type=_seconds, default=0)
    acq.set_defaults(func=lambda a: acquire(a.name, a.stale_minutes, a.wait_seconds))

    rel = sub.add_parser("release", help="drop the run lock")
    rel.add_argument("--name", required=True)
    rel.add_argument("--today", action="store_true", help="append the owner's date to NAME")
    rel.set_defaults(func=lambda a: release(a.name))

    args = parser.parse_args(argv)
    if not NAME_RE.fullmatch(args.name):
        sys.exit(f"error: --name {args.name!r} has characters not allowed in a lock name")
    if args.today:
        args.name = f"{args.name}-{owner_today().isoformat()}"
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
