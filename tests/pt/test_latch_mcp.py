"""latch_mcp.py: the one MCP session every pt-* script uses to reach the Mac."""
from __future__ import annotations

import pytest

import latch_mcp as lm
from latch_mcp import LatchError


class TestSettle:
    def test_pending_is_polled_until_ready(self):
        calls = []

        def get_result(handle):
            calls.append(handle)
            if len(calls) < 2:
                return {"status": "pending", "handle": handle}
            return {"status": "ready", "result": {"path": "/Users/test-owner/Plow/pt/x.b64"}}

        out = lm.settle({"status": "pending", "handle": "h1"}, get_result, sleep=lambda _n: None)
        assert out["path"] == "/Users/test-owner/Plow/pt/x.b64"
        assert calls == ["h1", "h1"]

    @pytest.mark.parametrize("status", ["denied", "failed", "expired", "blocked"])
    def test_a_refused_call_raises_with_its_status(self, status):
        with pytest.raises(LatchError, match=f"latch {status}"):
            lm.settle({"status": status, "handle": "h"}, lambda _h: {}, sleep=lambda _n: None)

    def test_a_blocked_call_carries_the_owner_action(self):
        blocked = {"status": "blocked", "diagnosis": {"owner_action": "Click Allow"}}
        with pytest.raises(LatchError, match="latch blocked: Click Allow"):
            lm.settle(blocked, lambda _h: {}, sleep=lambda _n: None)


class TestDecodeBody:
    @pytest.mark.parametrize("raw", [b"", b'{"jsonrpc": "2.0", "id": 1}', b"null", b'"result"'])
    def test_a_reply_with_no_result_or_error_is_refused(self, raw):
        with pytest.raises(LatchError, match="no result"):
            lm.decode_mcp_body("application/json", raw)

    def test_a_normal_reply_is_returned(self):
        body = b'{"jsonrpc":"2.0","id":1,"result":{"path":"/Users/test-owner/a"}}'
        assert lm.decode_mcp_body("application/json", body) == {
            "jsonrpc": "2.0", "id": 1, "result": {"path": "/Users/test-owner/a"},
        }


class TestUnwrap:
    def test_a_tool_error_raises_with_its_text(self):
        result = {"isError": True, "content": [
            {"type": "text", "text": "read failed: ENOENT: no such file or directory"}]}
        with pytest.raises(LatchError, match="ENOENT"):
            lm.unwrap_tool_result(result)

    def test_json_text_is_parsed(self):
        result = {"content": [{"type": "text", "text": '{"path": "/Users/test-owner/a", "content": "x"}'}]}
        assert lm.unwrap_tool_result(result) == {"path": "/Users/test-owner/a", "content": "x"}


class TestFinishCommand:
    @pytest.mark.parametrize("polled", [
        {"status": "blocked", "diagnosis": {"owner_action": "Click Allow"}},
        {"status": "blocked", "exit_code": 1, "diagnosis": {"owner_action": "Click Allow"}},
    ])
    def test_a_terminal_blocked_poll_reports_its_owner_action(self, polled):
        running = {"status": "running", "handle": "j"}
        with pytest.raises(LatchError, match="lp outcome unknown: Click Allow"):
            lm.finish_command(lambda *_: polled, running, "lp")

    def test_a_diagnosed_running_job_reports_its_owner_action(self):
        parked = {"status": "running", "handle": "j", "diagnosis": {"owner_action": "Click Allow"}}
        with pytest.raises(LatchError, match="lp outcome unknown: Click Allow"):
            lm.finish_command(lambda *_: {}, parked, "lp")


class TestConnect:
    """Which credential this install reaches the Mac with.

    One path, both install types: PLOW_MCP_URL, which plow-init publishes to
    every service from `/v1/agents/me` at boot. There is no static-credential
    branch -- see `test_a_stale_static_pair_is_ignored` for why.
    """

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for name in ("PLOW_AGENT_TOKEN", "PLOW_MCP_URL", "PLOW_API_BASE"):
            monkeypatch.delenv(name, raising=False)

    def test_a_stale_static_pair_is_ignored(self, monkeypatch):
        # The README used to have the owner paste a DOMO_* pair into the
        # home's .env, and that pair won here over the agent's own key. When
        # the pair went stale the relay answered 401 on every run while a
        # working credential sat unused beside it (measured 2026-09-22:
        # printing, edition recording and both desks' history all failed).
        monkeypatch.setenv("DOMO_DEVICE_UID", "stale-device")
        monkeypatch.setenv("DOMO_MCP_TOKEN", "revoked")
        monkeypatch.setenv("PLOW_MCP_URL", "https://plow-abc.int.exe.xyz/v1/relay/devices/usr-9/mcp")
        monkeypatch.setenv("PLOW_AGENT_TOKEN", "agent-token")

        client = lm.connect()

        assert client.url == "https://plow-abc.int.exe.xyz/v1/relay/devices/usr-9/mcp"
        assert client.token == "agent-token"

    def test_without_a_pair_it_uses_the_url_the_runtime_published(self, monkeypatch):
        # Deliberately a different host from PLOW_API_BASE: a proxied agent is
        # published a proxied URL, and rebuilding the path would discard it.
        monkeypatch.setenv("PLOW_API_BASE", "https://api.example")
        monkeypatch.setenv("PLOW_MCP_URL", "https://plow-abc.int.exe.xyz/v1/relay/devices/usr-9/mcp")
        monkeypatch.setenv("PLOW_AGENT_TOKEN", "agent-token")

        client = lm.connect()

        assert client.url == "https://plow-abc.int.exe.xyz/v1/relay/devices/usr-9/mcp"
        assert client.token == "agent-token"

    @pytest.mark.parametrize("present, missing", [
        ({"PLOW_AGENT_TOKEN": "t"}, "PLOW_MCP_URL"),
        ({"PLOW_MCP_URL": "https://x/mcp"}, "PLOW_AGENT_TOKEN"),
    ])
    def test_a_missing_runtime_value_is_refused_by_name(self, monkeypatch, present, missing):
        for name, value in present.items():
            monkeypatch.setenv(name, value)

        # LatchError, not SystemExit: SystemExit walks through every caller's
        # `except LatchError`, so the print leg would lose "page not printed".
        with pytest.raises(LatchError, match=missing):
            lm.connect()
