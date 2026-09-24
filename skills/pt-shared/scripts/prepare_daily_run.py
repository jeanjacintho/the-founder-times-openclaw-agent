#!/usr/bin/env python3
"""Archive prior daily scratch so a run cannot mistake it for today's work."""
from __future__ import annotations

import argparse
import os
from datetime import date, datetime
from pathlib import Path

from pt_paths import pt_home


def _dated_directory(name: str) -> bool:
    if len(name) != 10:
        return False
    try:
        date.fromisoformat(name)
        return True
    except ValueError:
        return False


def _daily_directory(name: str) -> bool:
    slot, separator, day = name.partition("-")
    suffix = slot.removeprefix("daily")
    return bool(separator) and slot.startswith("daily") and (not suffix or suffix.isdigit()) and _dated_directory(day)


def _scratch(path: Path, preserve_priority: bool = False) -> bool:
    if path.is_dir():
        if preserve_priority and path.name == "desk-priority":
            return False
        return (path.name.startswith("desk-") or _dated_directory(path.name)
                or _daily_directory(path.name))
    return path.name in {"chat-status.json", "seal-session.json"}


def prepare(pt_home: Path, now: datetime | None = None,
            preserve_priority: bool = False) -> Path | None:
    run = pt_home / "run"
    run.mkdir(parents=True, exist_ok=True)
    scratch = sorted(
        (path for path in run.iterdir() if _scratch(path, preserve_priority)),
        key=lambda path: path.name,
    )
    if not scratch:
        return None

    stamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    # Keep recoverable evidence outside the research tree.  The run agent is
    # told to inspect /var/lib/plow/pt, and exposing a fresh archive there
    # invited it to copy yesterday's notes instead of doing today's work.
    archive_root = pt_home.parent / f".{pt_home.name}-run-archives"
    archive_root.mkdir(exist_ok=True)
    archive = archive_root / f"run-{stamp}"
    suffix = 2
    while archive.exists():
        archive = archive_root / f"run-{stamp}-{suffix}"
        suffix += 1
    archive.mkdir()
    for path in scratch:
        path.replace(archive / path.name)
    return archive


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--preserve-priority", action="store_true",
        help="keep the accepted advisor checkpoint while clearing every other desk",
    )
    args = parser.parse_args()
    home = pt_home()
    prepare(home, preserve_priority=args.preserve_priority)
    # The caller needs only the clean-workspace result.  Do not advertise the
    # recovery path to the model that is about to research today's paper.
    print("READY")


if __name__ == "__main__":
    main()
