#!/usr/bin/env python3
"""chat_message_id.py -- a re-openable item for the owner's own Plow chat message.

An owner correction or setup answer is only a fact the paper may rest on when
it names an item that re-opens. A message the owner texted this agent's line
lives in the Plow chat, and the Plow API already gives it a uid -- the same
`GET /v1/chats/<uid>/messages` the channel plugin reads every turn with.

    chat_message_id.py                  HANDLE:plow_chat:<chat uid>:<message uid>
                                        of the owner's latest message, or HANDLE:none
    chat_message_id.py read <handle>    that message as JSON {uid, body, created_at,
                                        from_owner}, or NOT_FOUND (exit 1)

The bare call always exits 0 and fails closed: no owner chat yet, an HTTP
error, an answer of the wrong shape all print HANDLE:none, never a guessed id.
A handle for another chat, or any other reader's handle, is not this script's
(exit 2 on bad usage).
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bearer_http import TIMEOUT, open_no_redirect, require  # noqa: E402
from owner_chat import home_channel  # noqa: E402

PREFIX = "plow_chat:"
LATEST_LIMIT = 20
READ_LIMIT = 50
READ_PAGES = 10


def api_get(path):
    """One bearer GET against PLOW_API_BASE that never follows a redirect."""
    request = urllib.request.Request(
        url=f"{require('PLOW_API_BASE').rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {require('PLOW_AGENT_TOKEN')}", "Accept": "application/json"},
    )
    with open_no_redirect(request, timeout=TIMEOUT) as response:
        return json.loads(response.read())


def _page(get, chat, limit, after=None):
    path = f"/v1/chats/{chat}/messages?limit={limit}" + (f"&starting_after={after}" if after else "")
    data = get(path)
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise ValueError("messages page has no data list")
    return data["data"], bool(data.get("has_more"))


def _from_owner(message):
    sender = message.get("sender") or {}
    return (message.get("direction") == "inbound" and sender.get("type") == "member"
            and sender.get("role") == "owner")


def latest(get, chat):
    for message in _page(get, chat, LATEST_LIMIT)[0]:
        if isinstance(message, dict) and _from_owner(message) and message.get("uid"):
            return f"{PREFIX}{chat}:{message['uid']}"
    return None


def read(get, chat, handle):
    parts = handle[len(PREFIX):].split(":") if handle.startswith(PREFIX) else []
    if len(parts) != 2 or parts[0] != chat:
        return None
    after = None
    for _ in range(READ_PAGES):
        page, more = _page(get, chat, READ_LIMIT, after)
        for message in page:
            if isinstance(message, dict) and message.get("uid") == parts[1]:
                return {"uid": message["uid"], "body": message.get("body") or "",
                        "created_at": message.get("created_at") or "", "from_owner": _from_owner(message)}
        if not more or not page:
            return None
        after = page[-1].get("uid")
    return None


def main(argv=None, get=None, chat=None):
    argv = sys.argv[1:] if argv is None else argv
    get = get or api_get
    chat = chat or home_channel
    if argv and not (len(argv) == 2 and argv[0] == "read" and argv[1].startswith(PREFIX)):
        print("usage: chat_message_id.py | chat_message_id.py read plow_chat:<chat>:<message>", file=sys.stderr)
        return 2
    try:
        uid = chat()
        found = read(get, uid, argv[1]) if argv else latest(get, uid)
    except (SystemExit, OSError, ValueError, urllib.error.URLError):
        found = None
    if argv:
        print(json.dumps(found, ensure_ascii=False) if found else "NOT_FOUND")
        return 0 if found else 1
    print(f"HANDLE:{found}" if found else "HANDLE:none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
