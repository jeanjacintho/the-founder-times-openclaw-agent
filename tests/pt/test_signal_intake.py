"""signal_intake.py -- the only door a priority signal comes in through."""
from __future__ import annotations

import contextlib
import io
import json

import pytest

from conftest import load_module

intake = load_module("signal_intake", "pt-shared/scripts/signal_intake.py")

BASE = {"source": "group_chat", "from_name": "Maya", "chat_or_thread_id": "cht_1",
        "text": "Precisamos fechar a Acme até sexta", "received_at": "2026-09-24T12:03:01Z",
        "category": "priority", "item": "msg_1"}


@pytest.fixture
def pt_home(tmp_path, monkeypatch):
    home = tmp_path / "pt"
    home.mkdir()
    monkeypatch.setenv("PT_HOME", str(home))
    return home


def enable(pt_home, **sources):
    (pt_home / "config.json").write_text(json.dumps(
        {"signals": {"group_chat": False, "email": False, "imessage": False, **sources}}))


def run(record, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(record if isinstance(record, str) else json.dumps(record)))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = intake.main([])
    return code, json.loads(buf.getvalue())


def files(pt_home):
    return sorted((pt_home / "signals").glob("*.json")) if (pt_home / "signals").exists() else []


def test_priority_is_written_once(pt_home, monkeypatch):
    enable(pt_home, group_chat=True)
    code, out = run(BASE, monkeypatch)
    assert code == 0 and out["recorded"] is True
    [path] = files(pt_home)
    assert out["file"] == path.name and json.loads(path.read_text()) == BASE
    assert run(BASE, monkeypatch) == (0, {"recorded": False, "reason": "duplicate"})
    assert len(files(pt_home)) == 1


@pytest.mark.parametrize("category", ["spam", "fyi"])
def test_spam_and_fyi_never_become_a_signal(pt_home, monkeypatch, category):
    enable(pt_home, group_chat=True, email=True, imessage=True)
    for source in ("group_chat", "email", "imessage"):
        assert run({**BASE, "source": source, "category": category}, monkeypatch) == (
            0, {"recorded": False, "reason": f"category:{category}"})
    assert files(pt_home) == []


def test_disabled_source_is_refused(pt_home, monkeypatch):
    enable(pt_home, email=True)
    assert run(BASE, monkeypatch) == (0, {"recorded": False, "reason": "source-disabled:group_chat"})
    assert files(pt_home) == []


@pytest.mark.parametrize("config", [None, "{broken", json.dumps({"signals": "yes"}), json.dumps({"signals": {"group_chat": "true"}})])
def test_missing_or_unreadable_config_means_disabled(pt_home, monkeypatch, config):
    if config is not None:
        (pt_home / "config.json").write_text(config)
    assert run(BASE, monkeypatch)[1] == {"recorded": False, "reason": "source-disabled:group_chat"}


@pytest.mark.parametrize("text", ["", "   ", "[Attachment]", "[Email attachments are not supported.]"])
def test_empty_or_attachment_only_text_is_refused(pt_home, monkeypatch, text):
    enable(pt_home, group_chat=True)
    assert run({**BASE, "text": text}, monkeypatch) == (0, {"recorded": False, "reason": "empty-text"})


def test_long_text_is_capped(pt_home, monkeypatch):
    enable(pt_home, group_chat=True)
    run({**BASE, "text": "x" * 5000}, monkeypatch)
    [path] = files(pt_home)
    assert len(json.loads(path.read_text())["text"]) == 2000


@pytest.mark.parametrize("record", [{**BASE, "source": "sms"}, {**BASE, "received_at": "soon"}, "not json", "[1, 2]"])
def test_bad_contract_exits_2_and_writes_nothing(pt_home, monkeypatch, record):
    enable(pt_home, group_chat=True)
    code, out = run(record, monkeypatch)
    assert code == 2 and out["recorded"] is False and out["reason"].startswith("invalid:")
    assert files(pt_home) == []
