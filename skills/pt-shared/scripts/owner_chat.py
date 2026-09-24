#!/usr/bin/env python3
"""The owner's DM uid: PLOW_HOME_CHANNEL, or asked of Plow when that is blank.

    /opt/plow/skills/pt-shared/scripts/owner_chat.py     # prints the uid

Boot exports PLOW_HOME_CHANNEL when `/v1/agents/me` already lists the owner's
chat. A line whose owner has not texted yet has no such chat at boot, so the
variable stays blank until the next restart; this asks the same identity
endpoint again and applies the rule the Plow channel plugin uses
(`findOwnerChat`): the one active chat with exactly two participants, this
agent on its own line and a member whose role is owner. Nothing is cached or
written -- a uid pasted into config would outlive the chat it names.

Failure exits loudly by name, like bearer_http.require: a blank or ambiguous
answer must never read like "post nowhere".
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bearer_http import TIMEOUT, open_no_redirect, require  # noqa: E402


def find_owner_chat(identity: dict) -> str | None:
    """The owner's DM uid in an identity document, None when there is none yet."""
    line = (identity.get("line") or {}).get("uid")
    owners = [
        chat for chat in identity.get("chats") or []
        if chat.get("status") == "active"
        and len(chat.get("participants") or []) == 2
        and any(p.get("type") == "agent" and p.get("relationship") == "self"
                and (p.get("line") or {}).get("uid") == line for p in chat["participants"])
        and any(p.get("type") == "member" and p.get("role") == "owner" for p in chat["participants"])
    ]
    if len(owners) > 1:
        raise ValueError(f"expected one owner's chat; found {len(owners)}")
    return owners[0]["uid"] if owners else None


def fetch_identity(base: str, token: str) -> dict:
    request = urllib.request.Request(
        url=f"{base.rstrip('/')}/v1/agents/me",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with open_no_redirect(request, timeout=TIMEOUT) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        sys.exit(f"error: /v1/agents/me returned HTTP {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        sys.exit(f"error: GET /v1/agents/me failed: {exc.reason}")
    except ValueError as exc:
        sys.exit(f"error: /v1/agents/me returned a non-JSON response: {exc!r}")


def home_channel() -> str:
    """PLOW_HOME_CHANNEL when set, else the owner's chat from `/v1/agents/me`."""
    value = os.environ.get("PLOW_HOME_CHANNEL", "").strip()
    if value:
        return value
    identity = fetch_identity(require("PLOW_API_BASE"), require("PLOW_AGENT_TOKEN"))
    try:
        uid = find_owner_chat(identity)
    except ValueError as exc:
        sys.exit(f"error: PLOW_HOME_CHANNEL is not set and {exc}")
    if not uid:
        sys.exit("error: PLOW_HOME_CHANNEL is not set and the owner's chat does not exist yet")
    return uid


if __name__ == "__main__":
    print(home_channel())
