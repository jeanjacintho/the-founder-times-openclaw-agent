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

  acquire --name NAME [--stale-minutes N]
  release --name NAME

`acquire` prints exactly one word and always exits 0, so a cron-fired
session reads the decision instead of a status code:

  acquired        this process owns the run; release it when done
  stale-takeover  a lock was there but older than --stale-minutes, so it is
                  a dead run's leftover, not a live owner; this process now
                  owns it
  held            a fresh owner is running it; stop, do not start a second

`release` removes the lock; a missing lock is not an error (the run ended
without acquiring, or two releases raced). The lock directory is
`$PT_HOME/run` -- the same scratch space the notes live in, default
/var/lib/plow/pt.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys
from datetime import datetime, timezone

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


def acquire(name, stale_minutes):
    path = lock_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
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
            print("stale-takeover")
            return 0
        print("held")
        return 0
    with os.fdopen(fd, "w") as handle:
        handle.write(now().isoformat(timespec="seconds") + "\n")
    print("acquired")
    return 0


def release(name):
    path = lock_path(name)
    try:
        path.unlink()
        print("released")
    except FileNotFoundError:
        print("nothing-to-release")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    acq = sub.add_parser("acquire", help="take the run lock if free")
    acq.add_argument("--name", required=True)
    acq.add_argument("--stale-minutes", type=int, default=DEFAULT_STALE_MINUTES)
    acq.set_defaults(func=lambda a: acquire(a.name, a.stale_minutes))

    rel = sub.add_parser("release", help="drop the run lock")
    rel.add_argument("--name", required=True)
    rel.set_defaults(func=lambda a: release(a.name))

    args = parser.parse_args(argv)
    if not NAME_RE.fullmatch(args.name):
        sys.exit(f"error: --name {args.name!r} has characters not allowed in a lock name")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
