#!/usr/bin/env python3
"""signal_intake.py -- the only door a priority signal comes in through.

Reads one signal record (signals.py's contract) as JSON on stdin and prints
exactly one JSON line:

  {"recorded": true, "file": "<name>"}
  {"recorded": false, "reason": "category:spam" | "category:fyi"
                                | "source-disabled:<source>" | "empty-text"
                                | "duplicate"}              exit 0
  {"recorded": false, "reason": "invalid: <why>"}           exit 2

Only `priority` becomes a file: spam and fyi are classified and dropped, so
spam can never become a signal. A source the owner has not switched on in
`config.json` ("signals": {"group_chat", "email", "imessage"}) is refused;
a missing or unreadable config means every source is off. Both the channel
plugin (group chats) and the paper run (mail, iMessage) call this script.
"""
from __future__ import annotations

import json
import sys

import signals
from pt_paths import config_file

# What a turn carries when a message had no words of its own.
PLACEHOLDERS = {"[attachment]", "[email attachments are not supported.]"}


def source_enabled(source):
    try:
        config = json.loads(config_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    switches = config.get("signals") if isinstance(config, dict) else None
    return isinstance(switches, dict) and switches.get(source) is True


def intake(raw):
    try:
        record = signals.validate(json.loads(raw))
    except ValueError as error:
        return 2, {"recorded": False, "reason": f"invalid: {error}"}
    if record["category"] != "priority":
        return 0, {"recorded": False, "reason": f"category:{record['category']}"}
    if not source_enabled(record["source"]):
        return 0, {"recorded": False, "reason": f"source-disabled:{record['source']}"}
    if not record["text"] or record["text"].lower() in PLACEHOLDERS:
        return 0, {"recorded": False, "reason": "empty-text"}
    path = signals.write(record)
    if path is None:
        return 0, {"recorded": False, "reason": "duplicate"}
    return 0, {"recorded": True, "file": path.name}


def main(argv=None):
    code, result = intake(sys.stdin.read())
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
