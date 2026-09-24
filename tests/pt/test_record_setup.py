"""record_setup.py — the only way pt-setup writes .setup-draft.json."""
from __future__ import annotations

import json

import pytest

from conftest import load_module

record = load_module("record_setup", "pt-shared/scripts/record_setup.py")


def draft_of(tmp_path):
    return json.loads((tmp_path / ".setup-draft.json").read_text())


class TestNextQuestion:
    def test_empty_draft_asks_hour(self):
        assert record.next_question({}) == "hour"

    def test_hour_only_asks_printer(self):
        assert record.next_question({"local_hour": "07:00"}) == "printer"

    def test_blank_hour_still_asks_hour(self):
        assert record.next_question({"local_hour": "  "}) == "hour"

    def test_printer_without_configured_bool_asks_printer(self):
        draft = {"local_hour": "07:00", "printer": {"name": "HP"}}
        assert record.next_question(draft) == "printer"

    def test_hour_and_printer_asks_priority(self):
        draft = {"local_hour": "07:00", "printer": {"configured": False, "name": None}}
        assert record.next_question(draft) == "priority"

    def test_priority_is_asked_after_printer(self):
        draft = {"local_hour": "07:30", "printer": {"configured": False}}
        assert record.next_question(draft) == "priority"
        draft["priority"] = {"configured": True}
        assert record.next_question(draft) == "mail"

    def test_hour_printer_priority_asks_mail(self):
        draft = {"local_hour": "07:00", "printer": {"configured": False, "name": None},
                 "priority": {"configured": False}}
        assert record.next_question(draft) == "mail"

    def test_hour_printer_mail_asks_news(self):
        draft = {
            "local_hour": "07:00",
            "printer": {"configured": True, "name": "HP LaserJet 4"},
            "priority": {"configured": False},
            "mail": {"configured": False},
        }
        assert record.next_question(draft) == "news"

    def test_everything_present_is_close(self):
        draft = {
            "local_hour": "07:00",
            "printer": {"configured": True, "name": "HP LaserJet 4"},
            "priority": {"configured": True},
            "mail": {"configured": True},
            "news_asked": True,
            "signals": {"group_chat": False, "email": True, "imessage": False},
        }
        assert record.next_question(draft) == "close"

    def test_news_answered_asks_signals(self):
        draft = {"local_hour": "07:00", "printer": {"configured": False}, "priority": {"configured": True},
                 "mail": {"configured": True}, "news_asked": True}
        assert record.next_question(draft) == "signals"

    @pytest.mark.parametrize("signals", [
        {"group_chat": True},
        {"group_chat": True, "email": False, "imessage": "false"},
        "all",
    ])
    def test_incomplete_signals_is_still_open(self, signals):
        draft = {"local_hour": "07:00", "printer": {"configured": False}, "priority": {"configured": True},
                 "mail": {"configured": True}, "news_asked": True, "signals": signals}
        assert record.next_question(draft) == "signals"

    def test_printer_configured_string_not_bool_asks_printer(self):
        # A stray {"printer": {"configured": "true"}} (string, not bool) --
        # the gate and draft_line both require an actual JSON boolean.
        draft = {"local_hour": "07:00", "printer": {"configured": "true"}}
        assert record.next_question(draft) == "printer"


class TestApplyPairs:
    def test_top_level_string(self):
        draft = record.apply_pairs({}, ["local_hour=07:00"])
        assert draft == {"local_hour": "07:00"}

    def test_dotted_path_creates_nested_dict(self):
        draft = record.apply_pairs({}, ["printer.configured=true", "printer.name=HP"])
        assert draft == {"printer": {"configured": True, "name": "HP"}}

    def test_boolean_coercion_is_case_insensitive(self):
        draft = record.apply_pairs({}, ["mail.configured=FALSE"])
        assert draft["mail"]["configured"] is False

    def test_value_with_spaces_stays_one_string(self):
        # argv splitting happens in the shell, not here -- apply_pairs sees
        # the already-joined value as a single argv element.
        draft = record.apply_pairs({}, ["printer.name=HP LaserJet 4"])
        assert draft["printer"]["name"] == "HP LaserJet 4"

    def test_merges_into_existing_draft_without_clobbering_siblings(self):
        existing = {"printer": {"configured": True, "name": "HP"}}
        draft = record.apply_pairs(existing, ["printer.configured=false"])
        assert draft == {"printer": {"configured": False, "name": "HP"}}

    def test_no_equals_sign_raises(self):
        try:
            record.apply_pairs({}, ["local_hour"])
            raise AssertionError("expected ValueError")
        except ValueError:
            pass

    def test_blank_key_raises(self):
        try:
            record.apply_pairs({}, ["=07:00"])
            raise AssertionError("expected ValueError")
        except ValueError:
            pass


class TestCLI:
    def test_writes_draft_and_prints_next_question(self, tmp_path, capsys):
        config = tmp_path / "config.json"
        rc = record.main(["record_setup.py", str(config), "local_hour=07:00"])
        assert rc == 0
        out = capsys.readouterr().out.strip().splitlines()
        assert out == ["DRAFT:local_hour", "NEXT_QUESTION=printer"]
        assert draft_of(tmp_path) == {"local_hour": "07:00"}

    def test_second_call_advances_from_disk_state(self, tmp_path, capsys):
        config = tmp_path / "config.json"
        record.main(["record_setup.py", str(config), "local_hour=07:00"])
        capsys.readouterr()
        rc = record.main(
            ["record_setup.py", str(config), "printer.configured=true", "printer.name=HP LaserJet 4"]
        )
        assert rc == 0
        out = capsys.readouterr().out.strip().splitlines()
        assert out == ["DRAFT:local_hour,printer", "NEXT_QUESTION=priority"]
        assert draft_of(tmp_path) == {
            "local_hour": "07:00",
            "printer": {"configured": True, "name": "HP LaserJet 4"},
        }

    def test_full_sequence_reaches_close(self, tmp_path, capsys):
        config = tmp_path / "config.json"
        record.main(["record_setup.py", str(config), "local_hour=07:00"])
        record.main(["record_setup.py", str(config), "printer.configured=false"])
        record.main(["record_setup.py", str(config), "priority.configured=false"])
        record.main(["record_setup.py", str(config), "mail.configured=true"])
        capsys.readouterr()
        rc = record.main(["record_setup.py", str(config), "news_asked=true"])
        assert rc == 0
        out = capsys.readouterr().out.strip().splitlines()
        assert out == ["DRAFT:local_hour,printer,priority,mail", "NEXT_QUESTION=signals"]
        rc = record.main(["record_setup.py", str(config), "signals.group_chat=true",
                          "signals.email=false", "signals.imessage=false"])
        assert rc == 0
        out = capsys.readouterr().out.strip().splitlines()
        assert out == ["DRAFT:local_hour,printer,priority,mail,signals", "NEXT_QUESTION=close"]
        assert draft_of(tmp_path)["signals"] == {"group_chat": True, "email": False, "imessage": False}

    def test_too_few_args_is_a_usage_error(self, capsys):
        rc = record.main(["record_setup.py"])
        assert rc == 1
        assert "usage:" in capsys.readouterr().err

    def test_malformed_pair_is_a_named_failure_not_a_crash(self, tmp_path, capsys):
        config = tmp_path / "config.json"
        rc = record.main(["record_setup.py", str(config), "not-a-pair"])
        assert rc == 1
        assert "error:" in capsys.readouterr().err
        assert not (tmp_path / ".setup-draft.json").exists()

    def test_existing_draft_on_disk_is_preserved_and_extended(self, tmp_path, capsys):
        config = tmp_path / "config.json"
        (tmp_path / ".setup-draft.json").write_text(json.dumps({"local_hour": "08:30"}))
        capsys.readouterr()
        record.main(["record_setup.py", str(config), "printer.configured=true", "printer.name=Canon"])
        assert draft_of(tmp_path) == {
            "local_hour": "08:30",
            "printer": {"configured": True, "name": "Canon"},
        }


class TestDoneClearsTheDraft:
    """The close step tells pt-setup to delete .setup-draft.json. It used to
    say so with no command attached, and a live run reached for
    `python3 -c "import os; os.remove(...)"` -- tripping the dangerous-command
    gate and handing the owner an /approve prompt instead of their newspaper.
    Deleting the draft IS a draft write, so it goes through this script like
    every other one, as a bare invocation."""

    COMPLETE = {
        "local_hour": "07:00",
        "printer": {"configured": True, "name": "virtual_printer_online"},
        "priority": {"configured": False},
        "mail": {"configured": True},
        "news_asked": True,
        "signals": {"group_chat": False, "email": True, "imessage": False},
    }

    def write_draft(self, tmp_path, draft):
        path = tmp_path / ".setup-draft.json"
        path.write_text(json.dumps(draft), encoding="utf-8")
        return path

    def test_done_removes_a_complete_draft(self, tmp_path, capsys):
        draft_path = self.write_draft(tmp_path, self.COMPLETE)
        rc = record.main(["record_setup.py", str(tmp_path / "config.json"), "--done"])
        assert rc == 0
        assert not draft_path.exists()
        assert "DRAFT:cleared" in capsys.readouterr().out

    def test_done_is_idempotent_when_the_draft_is_already_gone(self, tmp_path, capsys):
        rc = record.main(["record_setup.py", str(tmp_path / "config.json"), "--done"])
        assert rc == 0
        assert "DRAFT:cleared" in capsys.readouterr().out

    def test_done_refuses_a_half_finished_draft(self, tmp_path, capsys):
        draft_path = self.write_draft(tmp_path, {"local_hour": "07:00"})
        rc = record.main(["record_setup.py", str(tmp_path / "config.json"), "--done"])
        assert rc == 1
        assert draft_path.exists(), "a mid-interview draft must survive"
        assert "printer" in capsys.readouterr().err

    def test_done_does_not_mix_with_key_value_pairs(self, tmp_path):
        self.write_draft(tmp_path, self.COMPLETE)
        rc = record.main(
            ["record_setup.py", str(tmp_path / "config.json"), "--done", "news_asked=true"]
        )
        assert rc == 1

