"""finalize_setup.py — the only way pt-setup writes pt/config.json.

Measured live (2026-09-16): the close step said "**Write**
/var/lib/plow/pt/config.json from the draft" and named no command, and no
script in the tree wrote that file. The run had every field it needed —
printer probed, timezone read, topics saved — ran the gate against a file
nobody had created, got "not valid JSON" (the gate collapses OSError into
that line) and told the owner the setup "hit a configuration error". Nothing
was wrong with the data; the file was simply never written.
"""
from __future__ import annotations

import json

import pytest

from conftest import load_module

finalize = load_module("finalize_setup", "pt-setup/scripts/finalize_setup.py")

COMPLETE = {
    "local_hour": "07:00",
    "printer": {"configured": True, "name": "virtual_printer_online"},
    "priority": {"configured": False},
    "mail": {"configured": True},
    "news_asked": True,
}


def seed(tmp_path, draft=None):
    (tmp_path / ".setup-draft.json").write_text(
        json.dumps(COMPLETE if draft is None else draft), encoding="utf-8"
    )
    return tmp_path / "config.json"


class TestWritesAValidConfig:
    def test_writes_config_that_passes_the_gate(self, tmp_path, capsys):
        config = seed(tmp_path)
        rc = finalize.main(
            ["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"]
        )
        out = capsys.readouterr().out
        assert rc == 0, out
        written = json.loads(config.read_text())
        assert written["owner"]["timezone"] == "America/Sao_Paulo"
        assert written["printer"] == {"configured": True, "name": "virtual_printer_online"}
        assert written["mail"]["configured"] is True
        assert written["delivery"]["lead_minutes"] == 0
        assert "CONFIG:written" in out

    @pytest.mark.parametrize(("hour", "lead"), [("07:00", 150), ("00:20", 150)])
    def test_priority_lead_minutes(self, tmp_path, hour, lead):
        # The lead covers pt-priority's three mandatory generations, so it is the tournament's own
        # 150-minute window. The nominal lead is stored unclamped -- 00:20 keeps its 150 here and
        # registration clamps it per slot. Chat still waits for the hour: lead is the start clock,
        # not the send clock.
        config = seed(tmp_path, dict(COMPLETE, local_hour=hour, priority={"configured": True}))
        finalize.main(["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"])
        assert json.loads(config.read_text())["delivery"]["lead_minutes"] == lead

    @pytest.mark.parametrize("container_tz", ["UTC", "", "Asia/Tokyo"])
    def test_stores_the_hour_the_owner_named_whatever_the_container_clock(
            self, tmp_path, monkeypatch, container_tz):
        # register_crons.py converts at registration; the config holds the
        # owner's wall clock and no container-clock copy of it.
        monkeypatch.setenv("TZ", container_tz)
        config = seed(tmp_path)
        assert finalize.main(
            ["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"]) == 0
        written = json.loads(config.read_text())
        assert written["delivery"]["hour"] == "07:00"
        assert "local_hour" not in written["delivery"]

    def test_printer_not_configured_writes_null_name(self, tmp_path):
        draft = dict(COMPLETE, printer={"configured": False})
        config = seed(tmp_path, draft)
        finalize.main(["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"])
        written = json.loads(config.read_text())
        assert written["printer"] == {"configured": False, "name": None}


class TestRefusesRatherThanWriteGarbage:
    def test_refuses_an_unfinished_interview(self, tmp_path, capsys):
        config = seed(tmp_path, {"local_hour": "07:00"})
        rc = finalize.main(
            ["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"]
        )
        assert rc == 1
        assert not config.exists(), "a refused finalize must not leave a partial config"
        assert "printer" in capsys.readouterr().err

    def test_refuses_a_missing_draft_with_a_clear_message(self, tmp_path, capsys):
        rc = finalize.main(
            ["finalize_setup.py", str(tmp_path / "config.json"), "--owner-tz", "America/Sao_Paulo"]
        )
        assert rc == 1
        err = capsys.readouterr().err
        assert "draft" in err and "not valid JSON" not in err

    def test_refuses_an_unknown_timezone(self, tmp_path, capsys):
        config = seed(tmp_path)
        rc = finalize.main(["finalize_setup.py", str(config), "--owner-tz", "Mars/Olympus"])
        assert rc == 1
        assert not config.exists()

    def test_reports_gate_failures_verbatim(self, tmp_path, capsys):
        # A draft that is "complete" but carries a printer with no name is
        # exactly what gate check 4 refuses; finalize must surface that, not
        # claim success.
        draft = dict(COMPLETE, printer={"configured": True, "name": "   "})
        config = seed(tmp_path, draft)
        rc = finalize.main(
            ["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"]
        )
        assert rc == 1
        assert "printer.name" in capsys.readouterr().err


class TestCarriesTheLanguage:
    """owner.language is gate check 7 and what a SCHEDULED edition writes in.
    pt-intake keeps it current from live chat, but a paper can be delivered
    before pt-intake ever runs, so setup must plant it."""

    def test_writes_owner_language_from_the_draft(self, tmp_path):
        draft = dict(COMPLETE, owner={"language": "Portuguese"})
        config = seed(tmp_path, draft)
        rc = finalize.main(["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"])
        assert rc == 0
        assert json.loads(config.read_text())["owner"]["language"] == "Portuguese"

    def test_omits_the_key_when_unrecorded(self, tmp_path):
        # Gate check 7: absent is valid. An invented default is not.
        config = seed(tmp_path)
        finalize.main(["finalize_setup.py", str(config), "--owner-tz", "America/Sao_Paulo"])
        assert "language" not in json.loads(config.read_text())["owner"]

