"""signals.py -- the priority-signal contract, in one place.

A signal is something someone else said (a group chat member, a mail sender,
an iMessage) that may change what the owner should do next. The advisor
tournament reads signals as labeled evidence, never as accepted fact.

One file per signal under `$PT_HOME/signals/`:

    <source>-<YYYYMMDDTHHMMSSZ>-<hash8>.json
    {"source": "group_chat" | "email" | "imessage", "from_name": str,
     "chat_or_thread_id": str, "text": str, "received_at": ISO-8601 UTC "Z",
     "category": "priority" | "fyi" | "spam", "item": str}

`item` re-opens the original (a Plow message uid, a Gmail thread id, an
iMessage rowid) and is the dedup key: `hash8` is sha256 of `source|item`, so
a replayed turn or a re-scanned window finds the file already there. Signals
older than RETENTION_DAYS are pruned on every write. signal_intake.py is the
only caller that writes; everything else reads.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from pt_paths import pt_home

SOURCES = ("group_chat", "email", "imessage")
CATEGORIES = ("priority", "fyi", "spam")
FIELDS = ("source", "from_name", "chat_or_thread_id", "text", "received_at", "category", "item")
MAX_TEXT = 2000
RETENTION_DAYS = 14


def signals_dir():
    return pt_home() / "signals"


def _utc(value):
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"received_at is not an ISO-8601 time: {value!r}") from None
    if parsed.tzinfo is None:
        raise ValueError(f"received_at has no UTC offset: {value!r}")
    return parsed.astimezone(timezone.utc)


def validate(record):
    """The record in canonical form, or ValueError naming the first bad field."""
    if not isinstance(record, dict):
        raise ValueError("record is not a JSON object")
    for field in FIELDS:
        if field not in record:
            raise ValueError(f"{field} is missing")
    extra = sorted(set(record) - set(FIELDS))
    if extra:
        raise ValueError(f"extra fields: {', '.join(extra)}")
    if record["source"] not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}: {record['source']!r}")
    if record["category"] not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}: {record['category']!r}")
    for field in ("from_name", "text"):
        if not isinstance(record[field], str):
            raise ValueError(f"{field} must be a string")
    for field in ("chat_or_thread_id", "item"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    received = _utc(record["received_at"])
    return {
        "source": record["source"],
        "from_name": record["from_name"].strip(),
        "chat_or_thread_id": record["chat_or_thread_id"].strip(),
        "text": record["text"].strip()[:MAX_TEXT],
        "received_at": received.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "category": record["category"],
        "item": record["item"].strip(),
    }


def _hash8(record):
    return hashlib.sha256(f"{record['source']}|{record['item']}".encode()).hexdigest()[:8]


def filename(record):
    stamp = _utc(record["received_at"]).strftime("%Y%m%dT%H%M%SZ")
    return f"{record['source']}-{stamp}-{_hash8(record)}.json"


def _received(path):
    """received_at from the file name; None for a name this module did not write."""
    parts = path.stem.split("-")
    if len(parts) != 3:
        return None
    try:
        return datetime.strptime(parts[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def prune(days=RETENTION_DAYS, now=None):
    """Delete signals received more than `days` ago; returns how many."""
    folder = signals_dir()
    if not folder.is_dir():
        return 0
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    removed = 0
    for path in folder.glob("*.json"):
        received = _received(path)
        if received is not None and received < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def write(record, *, now=None):
    """Write one validated signal atomically; None when it is already there."""
    record = validate(record)
    folder = signals_dir()
    folder.mkdir(parents=True, exist_ok=True)
    prune(now=now)
    if any(folder.glob(f"{record['source']}-*-{_hash8(record)}.json")):
        return None
    path = folder / filename(record)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def list_recent(days=RETENTION_DAYS, now=None):
    """Readable signals from the last `days`, newest first, each with its "file"."""
    folder = signals_dir()
    if not folder.is_dir():
        return []
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    found = []
    for path in folder.glob("*.json"):
        received = _received(path)
        if received is None or received < cutoff:
            continue
        try:
            record = validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
        found.append({**record, "file": path.name})
    return sorted(found, key=lambda r: (r["received_at"], r["file"]), reverse=True)
