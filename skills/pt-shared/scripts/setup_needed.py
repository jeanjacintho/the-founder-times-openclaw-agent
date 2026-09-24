#!/usr/bin/env python3
"""Print SETUP_NEEDED or READY for the live-chat first-run gate.

The Plow channel runs this before every owner DM turn and hands the
output to the model; AGENTS.md tells the model to run it itself when that
block is missing.
A missing file, unreadable JSON, or any of the three setup keys absent
is SETUP_NEEDED — load pt-setup, do not introduce a general assistant.
READY means the interview already finished; greetings are ordinary turns.

When SETUP_NEEDED, a second line names what `.setup-draft.json` already
holds (or DRAFT:none). Chat history is not progress: a wiped session
still shows old printer/mail turns in the Plow thread.

Exit 0 either way so a missing config is not mistaken for a crashed check.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pt_paths import config_file

_DELIVERY_HOUR_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
CONFIG_FILE = str(config_file())


def setup_needed(path):
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return True
    if not isinstance(config, dict):
        return True
    owner = config.get("owner")
    delivery = config.get("delivery")
    printer = config.get("printer")
    tz = owner.get("timezone") if isinstance(owner, dict) else None
    hour = delivery.get("hour") if isinstance(delivery, dict) else None
    configured = printer.get("configured") if isinstance(printer, dict) else None
    if not (isinstance(tz, str) and tz.strip()):
        return True
    if not (isinstance(hour, str) and _DELIVERY_HOUR_RE.fullmatch(hour)):
        return True
    if not isinstance(configured, bool):
        return True
    return False


def draft_line(config_path):
    """Second gate line: which interview fields the draft already holds."""
    draft_path = Path(config_path).with_name(".setup-draft.json")
    try:
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "DRAFT:none"
    if not isinstance(draft, dict):
        return "DRAFT:none"
    fields = []
    hour = draft.get("local_hour")
    if isinstance(hour, str) and hour.strip():
        fields.append("local_hour")
    printer = draft.get("printer")
    if isinstance(printer, dict) and isinstance(printer.get("configured"), bool):
        fields.append("printer")
    priority = draft.get("priority")
    if isinstance(priority, dict) and isinstance(priority.get("configured"), bool):
        fields.append("priority")
    mail = draft.get("mail")
    if isinstance(mail, dict) and isinstance(mail.get("configured"), bool):
        fields.append("mail")
    elif isinstance(draft.get("mail.configured"), bool):
        fields.append("mail")
    signals = draft.get("signals")
    if isinstance(signals, dict) and all(
            isinstance(signals.get(s), bool) for s in ("group_chat", "email", "imessage")):
        fields.append("signals")
    return "DRAFT:" + (",".join(fields) if fields else "none")


def _language_from(data):
    if not isinstance(data, dict):
        return None
    owner = data.get("owner")
    language = owner.get("language") if isinstance(owner, dict) else None
    if isinstance(language, str) and language.strip():
        return language.strip()
    return None


def owner_language(config_path):
    """The recorded language: draft first (setup), then config (READY).

    Empty string when neither file has a language. language_line() wraps
    this as LANG:…; chat_status.py --busy uses the same value.
    """
    config_path = Path(config_path)
    draft_path = config_path.with_name(".setup-draft.json")
    try:
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        draft = None
    from_draft = _language_from(draft)
    if from_draft:
        return from_draft
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = None
    return _language_from(config) or ""


def language_line(config_path):
    """LANG line for every gate reply: draft first (setup), then config (READY).

    This gate is the first action of EVERY live-chat reply, not only while
    setup is unfinished. Measured live 2026-09-18: READY printed no LANG
    line, so after one Portuguese turn the model kept writing Portuguese
    even when the owner switched back to English. The recorded language
    has to ride back on READY too, from pt/config.json, with the in-progress
    draft still winning while SETUP_NEEDED.
    """
    language = owner_language(config_path)
    return "LANG:" + language if language else "LANG:unrecorded"


def main(argv=None):
    argv = sys.argv if argv is None else argv
    path = argv[1] if len(argv) > 1 else CONFIG_FILE
    if setup_needed(path):
        print("SETUP_NEEDED")
        print(draft_line(path))
        print(language_line(path))
    else:
        print("READY")
        print(language_line(path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
