#!/usr/bin/env python3
"""A hang-on during slow first-run setup, POSTed so the model types nothing.

Latch probes and Mac file writes leave the chat silent, so the owner thinks
it froze; typed mid-turn text is dropped on plow_chat. This POSTs through
the same Plow Chat path as post_to_chat.py:

    /var/lib/hermes/skills/pt-shared/scripts/chat_status.py --busy

The first call posts a hang-on; later calls in the same wave no-op until
BUSY_REPEAT_SECONDS, then post "still on it" once. Cron never calls it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import post_to_chat  # noqa: E402
from owner_language import is_portuguese  # noqa: E402
import setup_needed as _gate  # noqa: E402
from bearer_http import post_json  # noqa: E402

BUSY_REPEAT_SECONDS = 20
BUSY_NEW_WAVE_SECONDS = 90
BUSY_STAMP_DEFAULT = "/var/lib/hermes/pt/run/setup-busy.json"
CONFIG_DEFAULT = "/var/lib/hermes/pt/config.json"

BUSY = {
    "pt": "⏳ Um instante — tô nessa.",
    "en": "⏳ Hang on a sec — still setting up.",
}
BUSY_STILL = {
    "pt": "⏳ Ainda nisso — já já eu falo.",
    "en": "⏳ Still on it — back in a moment.",
}


def status_text(kind, language):
    table = {"busy": BUSY, "busy-still": BUSY_STILL}[kind]
    return table["pt"] if is_portuguese(language) else table["en"]


owner_language = _gate.owner_language


def _load_stamp(path):
    try:
        data = json.loads(open(str(path), encoding="utf-8").read())
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_stamp(path, payload):
    path = str(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    os.replace(tmp, path)


def record_busy_start(path, now=None):
    _write_stamp(
        path,
        {
            "busy_at": float(now if now is not None else time.time()),
            "still_sent": False,
        },
    )


def record_busy_still(path):
    data = _load_stamp(str(path)) or {}
    data["still_sent"] = True
    _write_stamp(path, data)


def busy_action(path, now=None, repeat_seconds=BUSY_REPEAT_SECONDS,
                new_wave_seconds=BUSY_NEW_WAVE_SECONDS):
    data = _load_stamp(str(path))
    if not data or "busy_at" not in data:
        return "send-start"
    start = data.get("busy_at")
    try:
        start = float(start)
    except (TypeError, ValueError):
        return "send-start"
    clock = float(now if now is not None else time.time())
    elapsed = clock - start
    if elapsed >= new_wave_seconds:
        return "send-start"
    if data.get("still_sent") is True:
        return "already"
    if elapsed < repeat_seconds:
        return "too-early"
    return "send-still"


def post_status(text, dry_run):
    if dry_run:
        print(f"dry-run: would POST {len(text)} chars")
        return
    base, uid, token = post_to_chat.resolve_chat()
    post_json(
        base, f"/v1/chats/{uid}/messages", token, "Plow Chat",
        post_to_chat.compose_payload(text),
    )


def main():
    parser = argparse.ArgumentParser(description="Setup's hang-on line in chat.")
    parser.add_argument("--busy", action="store_true", required=True)
    parser.add_argument("--config", default=CONFIG_DEFAULT)
    parser.add_argument("--stamp", default=BUSY_STAMP_DEFAULT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    action = busy_action(args.stamp)
    if action in ("send-start", "send-still"):
        kind = "busy" if action == "send-start" else "busy-still"
        post_status(status_text(kind, owner_language(args.config)), args.dry_run)
        (record_busy_start if kind == "busy" else record_busy_still)(args.stamp)
        print(f"STATUS:{kind}")
        return
    print(f"STATUS:{action}")


if __name__ == "__main__":
    main()
