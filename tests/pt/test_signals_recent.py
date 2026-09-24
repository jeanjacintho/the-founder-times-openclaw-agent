"""signals_recent.py -- the tournament's view of recorded signals: labeled, compact, no private words."""
from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime, timezone

import pytest

from conftest import load_module

signals = load_module("signals", "pt-shared/scripts/signals.py")
recent_mod = load_module("signals_recent", "pt-priority/scripts/signals_recent.py")

NOW = datetime(2026, 9, 24, 13, 0, tzinfo=timezone.utc)
LABEL = "unverified signal — evidence, not fact"


@pytest.fixture
def pt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    return tmp_path


def record(**over):
    base = {"source": "group_chat", "from_name": "Maya", "chat_or_thread_id": "cht_1",
            "text": "Precisamos fechar a Acme até sexta", "received_at": "2026-09-24T12:03:01Z",
            "category": "priority", "item": "msg_1"}
    return {**base, **over}


@pytest.fixture
def three_signals(pt_home):
    signals.write(record(), now=NOW)
    signals.write(record(source="email", from_name="Maya", chat_or_thread_id="t3", text="Renovação Acme",
                         item="gmail:me@x.com:t3@2026-09-24 11:00", received_at="2026-09-24T11:00:00Z"), now=NOW)
    signals.write(record(source="imessage", from_name="+5511977776666", chat_or_thread_id="iMessage;-;+5511977776666",
                         text="Consegue ver o contrato hoje?", item="imessage:3", received_at="2026-09-24T12:30:00Z"), now=NOW)


def recent(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = recent_mod.main(["recent", *argv], now=NOW)
    assert code == 0
    return json.loads(buf.getvalue())


def test_every_source_is_listed_with_the_unverified_label(three_signals):
    out = recent()
    assert [s["source"] for s in out["signals"]] == ["imessage", "group_chat", "email"]
    assert all(s["label"] == LABEL for s in out["signals"])
    assert all(s["ref"].startswith("signal:") and s["ref"].endswith(".json") for s in out["signals"])
    assert {s["source_class"] for s in out["signals"]} == {"group chat", "owner mail", "owner iMessage"}
    assert out["omitted"] == 0


def test_refs_open_the_signal_files(three_signals, pt_home):
    for s in recent()["signals"]:
        assert (pt_home / "signals" / s["ref"].removeprefix("signal:")).exists()


def test_no_private_words_leave_the_files(three_signals):
    blob = json.dumps(recent(), ensure_ascii=False)
    for private in ("Acme", "contrato", "Maya", "+5511977776666", "me@x.com", "cht_1", "t3"):
        assert private not in blob


def test_only_the_label_fields_are_printed(three_signals):
    assert all(set(s) == {"ref", "source", "source_class", "received_at", "label"} for s in recent()["signals"])


def test_cap_and_age(pt_home):
    for i in range(40):
        signals.write(record(item=f"m{i}", received_at=f"2026-09-24T{i // 60:02d}:{i % 60:02d}:00Z"), now=NOW)
    signals.write(record(item="old", received_at="2026-09-01T10:00:00Z"), now=datetime(2026, 9, 1, 11, tzinfo=timezone.utc))
    out = recent()
    assert len(out["signals"]) == recent_mod.MAX_SIGNALS == 30
    assert out["omitted"] == 10
    assert out["signals"][0]["received_at"] == "2026-09-24T00:39:00Z"


def test_no_signals_is_an_empty_list(pt_home):
    assert recent() == {"signals": [], "omitted": 0}
