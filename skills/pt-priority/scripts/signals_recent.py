#!/usr/bin/env python3
"""signals_recent.py -- the recorded priority signals, as the tournament may see them.

    signals_recent.py recent

Prints one compact JSON object, newest first, at most MAX_SIGNALS:

    {"signals": [{"ref": "signal:<file>", "source": "group_chat" | "email" | "imessage",
                  "source_class": "group chat" | "owner mail" | "owner iMessage",
                  "received_at": "...Z", "label": "unverified signal — evidence, not fact"}],
     "omitted": <how many older ones did not fit>}

No words, names, handles or thread ids leave the files: Orient keeps these
refs in the root context and the run page, and only a child that re-opens
`/var/lib/plow/pt/signals/<file>` reads what was said. Signals older than
signals.RETENTION_DAYS are already gone.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pt-shared" / "scripts"))
import signals  # noqa: E402

MAX_SIGNALS = 30
LABEL = "unverified signal — evidence, not fact"
SOURCE_CLASS = {"group_chat": "group chat", "email": "owner mail", "imessage": "owner iMessage"}


def recent(now=None):
    found = signals.list_recent(now=now)
    listed = [{
        "ref": f"signal:{s['file']}", "source": s["source"], "source_class": SOURCE_CLASS[s["source"]],
        "received_at": s["received_at"], "label": LABEL,
    } for s in found[:MAX_SIGNALS]]
    return {"signals": listed, "omitted": max(0, len(found) - MAX_SIGNALS)}


def main(argv=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["recent"])
    parser.parse_args(sys.argv[1:] if argv is None else argv)
    print(json.dumps(recent(now or datetime.now(timezone.utc)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
