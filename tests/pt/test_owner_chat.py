import io
import json

import pytest

from conftest import load_module

owner_chat = load_module("owner_chat", "pt-shared/scripts/owner_chat.py")

SELF = {"type": "agent", "relationship": "self", "line": {"uid": "ln_phone"}}
OWNER = {"type": "member", "role": "owner", "uid": "mem_owner"}
GUEST = {"type": "member", "role": "member", "uid": "mem_guest"}


def identity(*chats):
    return {"line": {"uid": "ln_phone"}, "chats": list(chats)}


def chat(uid, *participants, status="active"):
    return {"uid": uid, "status": status, "participants": list(participants)}


class TestFindOwnerChat:
    def test_the_owner_dm_on_this_line(self):
        assert owner_chat.find_owner_chat(identity(chat("cht_dm", SELF, OWNER))) == "cht_dm"

    def test_groups_other_lines_and_closed_chats_are_not_the_dm(self):
        other_line = {**SELF, "line": {"uid": "ln_mail"}}
        doc = identity(
            chat("cht_group", SELF, OWNER, GUEST),
            chat("cht_mail", other_line, OWNER),
            chat("cht_closed", SELF, OWNER, status="archived"),
            chat("cht_guest", SELF, GUEST),
        )
        assert owner_chat.find_owner_chat(doc) is None

    def test_two_owner_dms_refuse_rather_than_guess(self):
        with pytest.raises(ValueError, match="found 2"):
            owner_chat.find_owner_chat(identity(chat("a", SELF, OWNER), chat("b", SELF, OWNER)))


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestHomeChannel:
    def test_the_exported_variable_wins_without_a_request(self, monkeypatch):
        monkeypatch.setenv("PLOW_HOME_CHANNEL", " cht_env ")
        monkeypatch.setattr(owner_chat, "open_no_redirect", lambda *a, **k: pytest.fail("no request expected"))
        assert owner_chat.home_channel() == "cht_env"

    def test_blank_variable_asks_the_identity_endpoint(self, monkeypatch):
        seen = {}

        def fake_open(request, *, timeout):
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            return FakeResponse(json.dumps(identity(chat("cht_dm", SELF, OWNER))).encode())

        monkeypatch.setenv("PLOW_HOME_CHANNEL", "")
        monkeypatch.setenv("PLOW_API_BASE", "http://api.test/")
        monkeypatch.setenv("PLOW_AGENT_TOKEN", "tok")
        monkeypatch.setattr(owner_chat, "open_no_redirect", fake_open)
        assert owner_chat.home_channel() == "cht_dm"
        assert seen == {"url": "http://api.test/v1/agents/me", "auth": "Bearer tok"}

    def test_no_owner_chat_yet_exits_by_name(self, monkeypatch):
        monkeypatch.delenv("PLOW_HOME_CHANNEL", raising=False)
        monkeypatch.setenv("PLOW_API_BASE", "http://api.test")
        monkeypatch.setenv("PLOW_AGENT_TOKEN", "tok")
        monkeypatch.setattr(owner_chat, "open_no_redirect",
                            lambda request, *, timeout: FakeResponse(json.dumps(identity()).encode()))
        with pytest.raises(SystemExit, match="owner's chat does not exist yet"):
            owner_chat.home_channel()

    def test_missing_credentials_exit_by_name(self, monkeypatch):
        monkeypatch.delenv("PLOW_HOME_CHANNEL", raising=False)
        monkeypatch.delenv("PLOW_API_BASE", raising=False)
        with pytest.raises(SystemExit, match="PLOW_API_BASE is not set"):
            owner_chat.home_channel()
