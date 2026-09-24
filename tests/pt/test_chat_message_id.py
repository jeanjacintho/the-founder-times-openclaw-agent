"""chat_message_id.py -- a re-openable item for the owner's own Plow chat message."""
from __future__ import annotations

import contextlib
import io
import json

import pytest

from conftest import load_module

cmid = load_module("chat_message_id", "pt-shared/scripts/chat_message_id.py")

OWNER = {"type": "member", "uid": "mem_owner", "role": "owner", "display_name": "Owner"}
GUEST = {"type": "member", "uid": "mem_guest", "role": "member", "display_name": "Guest"}
AGENT = {"type": "agent", "relationship": "self", "line": {"uid": "ln_1"}}


def msg(uid, sender, body="x", direction="inbound"):
    return {"uid": uid, "direction": direction, "sender": sender, "body": body,
            "created_at": "2026-09-24T12:00:00Z", "attachments": []}


class FakeApi:
    """GET /v1/chats/<chat>/messages, newest first, paged by starting_after."""

    def __init__(self, messages, fail=None):
        self.messages = messages
        self.fail = fail
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        if self.fail:
            raise self.fail
        assert path.startswith("/v1/chats/cht_home/messages?limit=")
        after = path.split("starting_after=")[1] if "starting_after=" in path else None
        start = next(i + 1 for i, m in enumerate(self.messages) if m["uid"] == after) if after else 0
        limit = int(path.split("limit=")[1].split("&")[0])
        page = self.messages[start:start + limit]
        return {"data": page, "has_more": start + limit < len(self.messages)}


def run(argv, api, chat="cht_home"):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cmid.main(argv, get=api.get, chat=lambda: chat)
    return code, out.getvalue().strip()


def test_the_owners_latest_message_is_the_handle():
    api = FakeApi([msg("m5", AGENT, direction="outbound"), msg("m4", OWNER, "Raj is my cousin"), msg("m3", OWNER)])
    assert run([], api) == (0, "HANDLE:plow_chat:cht_home:m4")


def test_no_owner_message_is_none():
    assert run([], FakeApi([msg("m2", AGENT, direction="outbound"), msg("m1", GUEST)])) == (0, "HANDLE:none")


@pytest.mark.parametrize("failure", [OSError("unreachable"), ValueError("not json"), SystemExit("error: HTTP 401")])
def test_any_failure_fails_closed_to_none(failure):
    assert run([], FakeApi([], fail=failure)) == (0, "HANDLE:none")


def test_no_owner_chat_is_none():
    def no_chat():
        raise SystemExit("error: the owner's chat does not exist yet")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cmid.main([], get=FakeApi([]).get, chat=no_chat)
    assert (code, out.getvalue().strip()) == (0, "HANDLE:none")


def test_read_reopens_a_handle_across_pages():
    older = [msg(f"m{i}", OWNER, f"body {i}") for i in range(120, 0, -1)]
    api = FakeApi(older)
    code, out = run(["read", "plow_chat:cht_home:m7"], api)
    assert code == 0
    assert json.loads(out) == {"uid": "m7", "body": "body 7", "created_at": "2026-09-24T12:00:00Z", "from_owner": True}
    assert len(api.paths) >= 2, "it had to page back past the first page"


def test_read_an_unknown_or_foreign_handle_is_not_found():
    api = FakeApi([msg("m1", OWNER)])
    assert run(["read", "plow_chat:cht_home:m404"], api) == (1, "NOT_FOUND")
    assert run(["read", "plow_chat:cht_other:m1"], api, chat="cht_home")[0] == 1
    assert run(["read", "imessage:12"], api) == (2, "")


def test_read_failure_is_not_found_never_a_guess():
    assert run(["read", "plow_chat:cht_home:m1"], FakeApi([], fail=OSError("x"))) == (1, "NOT_FOUND")
