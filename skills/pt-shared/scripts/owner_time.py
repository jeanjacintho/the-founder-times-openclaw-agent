#!/usr/bin/env python3
"""owner_time.py -- the owner's own clock, from pt/config.json, not the
container's.

register_crons.py no longer requires the container's TZ to equal
owner.timezone (see its module docstring): pt-setup converts the owner's
stated local time into the container's local hour once, at write time, but
never touches the container's own TZ. A page named for the owner's day, or
a heading stamped with the owner's own hour, can therefore land a day (or
an hour) off whatever the container's clock reads. Two callers need the
owner's own now -- history.py's seven-day window, record_edition.py's
`## HH:MM edition` heading and `created`/`updated` -- so this is their one
shared source instead of two.

owner_now()/owner_today() fall back to the container's own clock only when
the config file or the owner.timezone key is genuinely absent. A config
that exists but can't be trusted (bad JSON, an unreadable file, an unknown
zone name) raises instead of guessing -- a silently wrong window or heading
would read as valid.

CLI, for a scheduled paper checking its own window (pt-priority Orient):

    owner_time.py minutes-until HH:MM

prints the whole minutes from now until HH:MM today on the owner's clock --
negative once it has passed, never rolled over to tomorrow. Bad usage: exit 2.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pt_paths import config_file

# A sentinel, not a Path: PT_HOME (tests point it at a tmp dir, same as
# topics.py/run_lock.py/record_edition.py) has to be read at call time, not
# baked in as a default at import time.
CONFIG = object()


def _config_path(config_path):
    if config_path is not CONFIG:
        return config_path
    return config_file()


def owner_now(config_path=CONFIG):
    """An aware datetime in the owner's own zone."""
    try:
        config = json.loads(Path(_config_path(config_path)).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return datetime.now().astimezone()
    try:
        tz = config["owner"]["timezone"]
    except (KeyError, TypeError):
        return datetime.now().astimezone()
    return datetime.now(ZoneInfo(tz))


def owner_today(config_path=CONFIG):
    return owner_now(config_path).date()


HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def minutes_until(hhmm, config_path=CONFIG):
    """Whole minutes from the owner's now until HH:MM of the owner's today."""
    match = HHMM.match(hhmm)
    if not match:
        raise ValueError(f"not an HH:MM time: {hhmm!r}")
    now = owner_now(config_path)
    target = now.replace(hour=int(match.group(1)), minute=int(match.group(2)), second=0, microsecond=0)
    return int((target - now).total_seconds() // 60)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] != "minutes-until":
        print("usage: owner_time.py minutes-until HH:MM", file=sys.stderr)
        return 2
    try:
        print(minutes_until(argv[1]))
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
