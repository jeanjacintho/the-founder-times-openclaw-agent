#!/usr/bin/env python3
"""set_signal_source.py -- switch one priority-signal source on or off.

    set_signal_source.py <group_chat|email|imessage> <on|off>

After setup, "turn on email" / "stop listening to groups" is one call here,
never a hand-edited config.json. The other sources keep their switches (a
config from before signals gets the block with the rest off). The result is
validated by pt_config_gate.py BEFORE it replaces the file, and written
atomically. Prints one line:

    SIGNALS:group_chat=<on|off>,email=<on|off>,imessage=<on|off>

A bad argument, a missing config or one the gate refuses changes nothing:
`error: …` on stderr, exit 1. Probing the Mac before switching email or
iMessage on is pt-setup's job, not this script's.
"""
from __future__ import annotations

import json
import os
import sys

import pt_config_gate as _gate
from pt_paths import config_file

SOURCES = _gate.SIGNAL_SOURCES
STATES = {"on": True, "off": False}


def fail(message):
    print(f"error: {message}", file=sys.stderr)
    return 1


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] not in SOURCES or argv[1] not in STATES:
        return fail(f"usage: set_signal_source.py <{'|'.join(SOURCES)}> <on|off>")
    source, state = argv[0], STATES[argv[1]]
    path = config_file()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return fail(f"no config at {path}; finish setup first")
    except (OSError, ValueError) as error:
        return fail(f"config is not readable: {error}")
    if not isinstance(config, dict):
        return fail("config is not a JSON object")
    current = config.get("signals") if isinstance(config.get("signals"), dict) else {}
    config["signals"] = {s: current.get(s) is True for s in SOURCES}
    config["signals"][source] = state
    failures = _gate.gate(config)
    if failures:
        return fail(failures)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    print("SIGNALS:" + ",".join(f"{s}={'on' if config['signals'][s] else 'off'}" for s in SOURCES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
