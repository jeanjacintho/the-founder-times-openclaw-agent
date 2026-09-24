"""signals.py -- the priority-signal contract and its one writer."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from conftest import load_module

signals = load_module("signals", "pt-shared/scripts/signals.py")

NOW = datetime(2026, 9, 24, 13, 0, tzinfo=timezone.utc)
BASE = {"source": "group_chat", "from_name": "Maya", "chat_or_thread_id": "cht_1",
        "text": "Precisamos fechar a Acme até sexta", "received_at": "2026-09-24T12:03:01Z",
        "category": "priority", "item": "msg_1"}


@pytest.fixture
def pt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))
    return tmp_path / "pt"


def test_validate_keeps_the_contract_exactly():
    assert signals.validate(dict(BASE)) == BASE


@pytest.mark.parametrize("field, value", [
    ("source", "sms"), ("category", "urgent"), ("received_at", "yesterday"),
    ("from_name", 7), ("item", ""), ("chat_or_thread_id", None),
])
def test_validate_names_the_bad_field(field, value):
    with pytest.raises(ValueError, match=field):
        signals.validate({**BASE, field: value})


def test_validate_refuses_missing_and_extra_fields():
    with pytest.raises(ValueError, match="text"):
        signals.validate({k: v for k, v in BASE.items() if k != "text"})
    with pytest.raises(ValueError, match="extra"):
        signals.validate({**BASE, "extra": 1})


def test_offset_time_is_stored_in_utc():
    record = signals.validate({**BASE, "received_at": "2026-09-24T09:03:01-03:00"})
    assert record["received_at"] == "2026-09-24T12:03:01Z"


def test_text_is_stripped_and_capped():
    record = signals.validate({**BASE, "text": "  " + "x" * 5000 + "  "})
    assert record["text"] == "x" * signals.MAX_TEXT


def test_filename_is_stable_per_source_and_item():
    name = signals.filename(signals.validate(dict(BASE)))
    assert name.startswith("group_chat-20260924T120301Z-") and name.endswith(".json")
    assert name == signals.filename(signals.validate({**BASE, "text": "other words"}))
    assert name != signals.filename(signals.validate({**BASE, "item": "msg_2"}))


def test_write_is_atomic_and_deduplicated(pt_home):
    path = signals.write(dict(BASE), now=NOW)
    assert json.loads(path.read_text()) == BASE
    assert signals.write({**BASE, "received_at": "2026-09-24T12:05:00Z"}, now=NOW) is None
    assert sorted(p.name for p in (pt_home / "signals").iterdir()) == [path.name]


def test_prune_drops_only_old_signals(pt_home):
    then = datetime(2026, 9, 1, 11, tzinfo=timezone.utc)
    old = signals.write({**BASE, "item": "old", "received_at": "2026-09-01T10:00:00Z"}, now=then)
    fresh = signals.write({**BASE, "item": "fresh"}, now=then)
    assert old.exists() and fresh.exists()
    assert signals.prune(now=NOW) == 1
    assert not old.exists() and fresh.exists()


def test_write_prunes_as_it_goes(pt_home):
    old = signals.write({**BASE, "item": "old", "received_at": "2026-09-01T10:00:00Z"}, now=datetime(2026, 9, 1, 11, tzinfo=timezone.utc))
    signals.write({**BASE, "item": "new"}, now=NOW)
    assert not old.exists()


def test_list_recent_is_newest_first_and_names_the_file(pt_home):
    signals.write({**BASE, "item": "a", "received_at": "2026-09-23T08:00:00Z"}, now=NOW)
    signals.write({**BASE, "item": "b", "source": "email", "received_at": "2026-09-24T08:00:00Z"}, now=NOW)
    recent = signals.list_recent(now=NOW)
    assert [r["item"] for r in recent] == ["b", "a"]
    assert all((pt_home / "signals" / r["file"]).exists() for r in recent)


def test_list_recent_skips_unreadable_files(pt_home):
    signals.write(dict(BASE), now=NOW)
    (pt_home / "signals" / "email-20260924T000000Z-deadbeef.json").write_text("{not json")
    assert [r["item"] for r in signals.list_recent(now=NOW)] == ["msg_1"]


def test_empty_home_lists_nothing(pt_home):
    assert signals.list_recent(now=NOW) == []
    assert signals.prune(now=NOW) == 0
