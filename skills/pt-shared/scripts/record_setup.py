#!/usr/bin/env python3
"""record_setup.py -- the ONLY way pt-setup writes .setup-draft.json.

Measured live (2026-09-14): after the owner accepted the default hour, the
model wrote the draft itself with a free-form `write_file` call, then went
on -- same turn -- to probe the printer through Latch and ask about the
letters desk, all before the owner ever saw "is a printer set up on your
Mac?" as its own question. The draft never got a `printer` key at all: the
probe's answer was used to phrase a reply and then dropped. Prose telling
the model "ask one question, then stop" was not enough to stop that.

This script is the fix: pt-setup never hand-edits .setup-draft.json again.
Every answer is recorded here, and the script -- not the model's own
judgement -- says what to ask next.

Usage:

    record_setup.py <config.json path> key=value [key=value ...]
    record_setup.py <config.json path> --done

`--done` is the close step's last act: it deletes the draft and prints
DRAFT:cleared. It is idempotent (an already-deleted draft is success) and it
REFUSES a draft whose interview is unfinished, naming what is still missing --
the draft is the only record of how far setup got, and a wrong delete re-asks
the owner everything.

Each `key` is a dot-path merged into `.setup-draft.json` (a sibling file of
<config.json path>); a key with no dot is a top-level field. "true"/"false"
(any case) parse as booleans, everything else is kept as a string -- so
"07:00" is written as the string "07:00", and "true"/"false" for
printer.configured / priority.configured / mail.configured are real JSON booleans, not the
strings "true"/"false" (the gate and setup_needed.py's draft_line both
require isinstance(..., bool)).

A value containing a space needs its own shell quoting, same as any other
command argument -- e.g. printer.name="HP LaserJet 4" -- nothing here reads
JSON off argv, so there is no `{`/`}`/inner-quote escaping to get wrong.

Prints two lines on success:

    DRAFT:<comma-joined fields already recorded, or "none">
    NEXT_QUESTION=<hour|printer|priority|mail|news|signals|close>

pt-setup's SKILL.md reads NEXT_QUESTION to decide what to ask -- never by
re-deriving "what's next" from the draft's shape itself, and never from
what the chat thread already discussed. Ask exactly that one thing, then
stop; do not also perform the step after it in the same reply.

Exit 0 on success. A malformed key=value pair, or a draft file that isn't a
JSON object, is a named failure on stderr, exit 1 -- still a bare script
invocation with no interpreter wrapping, so SOUL.md's script-execution gate
stays satisfied even when this fails.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import setup_needed as _gate  # noqa: E402 -- sibling script; reuse draft_line
from pt_paths import config_file  # noqa: E402

DEFAULT_CONFIG = str(config_file())
# The order pt-setup/SKILL.md's questions are asked in, plus the close step.
# next_question() returns the first of these whose draft field is missing.
QUESTION_ORDER = ("hour", "printer", "priority", "mail", "news", "signals")
# The priority-signal sources question 5 switches; all three must be recorded.
SIGNAL_SOURCES = ("group_chat", "email", "imessage")


def _coerce(raw_value):
    if raw_value.lower() == "true":
        return True
    if raw_value.lower() == "false":
        return False
    return raw_value


def _set_dotted(draft, dotted_key, value):
    parts = [p for p in dotted_key.split(".") if p]
    if not parts:
        raise ValueError(f"blank key in: {dotted_key!r}")
    node = draft
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def load_draft(draft_path):
    try:
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return draft if isinstance(draft, dict) else {}


def apply_pairs(draft, pairs):
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"not a key=value pair: {pair!r}")
        key, _, raw_value = pair.partition("=")
        _set_dotted(draft, key.strip(), _coerce(raw_value))
    return draft


def next_question(draft):
    """The first interview field still missing from the draft, in
    pt-setup/SKILL.md's own question order. `news` has no stored value of
    its own (naming zero topics is a valid answer) -- record_setup.py is
    called with news_asked=true once that question has been asked and
    answered (even "nothing for now"), the same way every other step
    advances only once its own field lands in the draft."""
    hour = draft.get("local_hour")
    if not (isinstance(hour, str) and hour.strip()):
        return "hour"
    printer = draft.get("printer")
    if not (isinstance(printer, dict) and isinstance(printer.get("configured"), bool)):
        return "printer"
    priority = draft.get("priority")
    if not (isinstance(priority, dict) and isinstance(priority.get("configured"), bool)):
        return "priority"
    mail = draft.get("mail")
    if not (isinstance(mail, dict) and isinstance(mail.get("configured"), bool)):
        return "mail"
    if not isinstance(draft.get("news_asked"), bool):
        return "news"
    signals = draft.get("signals")
    if not (isinstance(signals, dict) and all(isinstance(signals.get(s), bool) for s in SIGNAL_SOURCES)):
        return "signals"
    return "close"


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) < 3:
        print(
            "usage: record_setup.py <config.json path> key=value [key=value ...]\n"
            "       record_setup.py <config.json path> --done",
            file=sys.stderr,
        )
        return 1
    config_path = Path(argv[1])
    draft_path = config_path.with_name(".setup-draft.json")
    if "--done" in argv[2:]:
        # The close step's last act. Deleting the draft is a draft write, so
        # it goes through this script like every other one -- pt-setup used to
        # be told "delete .setup-draft.json" with no command attached, and a
        # live run reached for an inline interpreter to do it, tripping the
        # dangerous-command gate in front of the owner.
        if len(argv) != 3:
            print("error: --done takes no other arguments", file=sys.stderr)
            return 1
        if draft_path.exists():
            pending = next_question(load_draft(draft_path))
            # Refuse to throw away an interview still in progress: the draft is
            # the ONLY record of how far setup got, and a wrong delete re-asks
            # the owner everything.
            if pending != "close":
                print(
                    f"error: setup is not finished (still needs: {pending}); "
                    "refusing to clear the draft",
                    file=sys.stderr,
                )
                return 1
            draft_path.unlink()
        print("DRAFT:cleared")
        return 0
    draft = load_draft(draft_path)
    try:
        apply_pairs(draft, argv[2:])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
    print(_gate.draft_line(config_path))
    print(f"NEXT_QUESTION={next_question(draft)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
