"""chat_status.py --busy -- a hang-on, never a play-by-play."""
from __future__ import annotations

import json

import pytest

from conftest import load_module

status = load_module("chat_status", "pt-shared/scripts/chat_status.py")


class TestCopy:
    def test_setup_busy_is_a_hang_on_not_a_play_by_play(self):
        start = status.status_text("busy", "Portuguese")
        still = status.status_text("busy-still", "pt-BR")
        assert start.startswith("⏳ ")
        assert still.startswith("⏳ ")
        assert start != still
        for line in (start, still):
            assert "`" not in line
            assert "latch" not in line.lower()
            assert "desk" not in line.lower()
            assert "arquivo" not in line.lower()
            assert "file" not in line.lower()
        en = status.status_text("busy", "English")
        assert en.startswith("⏳ ")
        assert "jornal" not in en.lower()

    def test_unknown_kind_fails_loudly(self):
        with pytest.raises(KeyError):
            status.status_text("not-a-kind", "English")


class TestBusyGate:
    @pytest.mark.parametrize(
        "prep,now,expected",
        [
            (None, 1000.0, "send-start"),
            ("start", 1008.0, "too-early"),
            ("start", 1000.0 + status.BUSY_REPEAT_SECONDS + 1, "send-still"),
            (
                "start-still",
                1000.0 + status.BUSY_REPEAT_SECONDS + 6,
                "already",
            ),
            (
                "start-still",
                1000.0 + status.BUSY_NEW_WAVE_SECONDS + 1,
                "send-start",
            ),
        ],
    )
    def test_busy_wave(self, tmp_path, prep, now, expected):
        stamp = tmp_path / "setup-busy.json"
        if prep in ("start", "start-still"):
            status.record_busy_start(stamp, now=1000.0)
        if prep == "start-still":
            status.record_busy_still(stamp)
        assert status.busy_action(stamp, now=now) == expected


class TestLanguageFromConfig:
    def test_reads_owner_language(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text(
            json.dumps({"owner": {"language": "Portuguese"}}), encoding="utf-8"
        )
        assert status.owner_language(cfg) == "Portuguese"

    def test_setup_draft_wins_during_the_interview(self, tmp_path):
        cfg = tmp_path / "config.json"
        cfg.write_text(
            json.dumps({"owner": {"language": "English"}}), encoding="utf-8"
        )
        (tmp_path / ".setup-draft.json").write_text(
            json.dumps({"owner": {"language": "Portuguese"}}), encoding="utf-8"
        )
        assert status.owner_language(cfg) == "Portuguese"


def test_a_written_language_waits_in_its_own_words(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    phrases = load_module("owner_phrases", "pt-shared/scripts/owner_phrases.py")
    table = {k: "ZH " + v for k, v in phrases.SOURCE.items()}
    (tmp_path / "owner-phrases.json").write_text(json.dumps({"language": "Mandarin Chinese", "phrases": table}))
    assert status.status_text("busy", "Mandarin Chinese") == "ZH ⏳ Hang on a sec — still setting up."
    assert status.status_text("busy", "Deutsch") == "⏳ Hang on a sec — still setting up."
    assert status.status_text("busy", "Português") == "⏳ Um instante — tô nessa."
