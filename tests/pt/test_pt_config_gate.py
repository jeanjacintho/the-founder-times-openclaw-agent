"""The pt-config gate's invariants: the single definition of a valid config."""
from __future__ import annotations

import json

import pytest

from conftest import load_module

gate_mod = load_module("pt_config_gate", "pt-shared/scripts/pt_config_gate.py")


def run_gate(config, tmp_path):
    path = tmp_path / "config.json"
    if isinstance(config, str):
        path.write_text(config)
    else:
        path.write_text(json.dumps(config))
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        # main takes sys.argv (argv[1] is the path), not bare args.
        code = gate_mod.main(["pt_config_gate.py", str(path)])
    return buf.getvalue().strip(), code


VALID = {
    "owner": {"timezone": "America/Los_Angeles"},
    "delivery": {"hour": "07:00"},
    "printer": {"configured": False, "name": None},
}


class TestPass:
    def test_valid_config_is_silent(self, tmp_path):
        out, code = run_gate(VALID, tmp_path)
        assert out == ""
        assert code == 0

    def test_printer_name_optional_when_unconfigured(self, tmp_path):
        out, _ = run_gate({**VALID, "printer": {"configured": False}}, tmp_path)
        assert out == ""

    def test_configured_printer_with_name_passes(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "printer": {"configured": True, "name": "HP_LaserJet"}},
            tmp_path,
        )
        assert out == ""

    def test_lead_minutes_optional(self, tmp_path):
        out, _ = run_gate(VALID, tmp_path)
        assert out == ""

    @pytest.mark.parametrize("lead", [0, 45, 179, 180, 1000])
    def test_lead_minutes_accepted(self, tmp_path, lead):
        out, _ = run_gate(
            {**VALID, "delivery": {"hour": "07:00", "lead_minutes": lead}}, tmp_path
        )
        assert out == ""


class TestNotValidJSON:
    def test_unreadable_file(self, tmp_path):
        out, _ = run_gate(str(tmp_path / "missing.json"), tmp_path)
        assert out == "not valid JSON"

    def test_garbage(self, tmp_path):
        out, _ = run_gate("garbage", tmp_path)
        assert out == "not valid JSON"

    def test_non_object_top_level(self, tmp_path):
        out, _ = run_gate([1, 2], tmp_path)
        assert out == "not valid JSON"

    def test_non_string_timezone_collapses(self, tmp_path):
        out, _ = run_gate({**VALID, "owner": {"timezone": 42}}, tmp_path)
        assert out == "not valid JSON"

    def test_nan_fail_closes(self, tmp_path):
        out, _ = run_gate(
            '{"owner": {"timezone": "UTC"}, "delivery": {"hour": "07:00"},'
            ' "printer": {"configured": NaN}}',
            tmp_path,
        )
        assert out == "not valid JSON"


class TestInvariants:
    def test_blank_timezone(self, tmp_path):
        out, _ = run_gate({**VALID, "owner": {"timezone": "   "}}, tmp_path)
        assert "owner.timezone is blank" in out

    def test_blank_string_timezone(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "owner": {"timezone": "\t"}}, tmp_path
        )
        assert "owner.timezone is blank" in out

    @pytest.mark.parametrize("hour", ["7:00", "24:00", "0700", "07:60", 700, None])
    def test_malformed_delivery_hour(self, tmp_path, hour):
        out, _ = run_gate({**VALID, "delivery": {"hour": hour}}, tmp_path)
        assert 'delivery.hour is not "HH:MM"' in out

    @pytest.mark.parametrize("hour", ["07:30", "10:25", "00:05", "23:59"])
    def test_delivery_hour_accepts_any_real_minute(self, tmp_path, hour):
        # Minutes were once refused on the theory that "the cron fires at
        # the hour" was a hard limit -- register_crons.py's own
        # daily_schedule() has always produced a non-zero minute field, so
        # any real HH:MM is a promise the schedule can keep.
        out, _ = run_gate({**VALID, "delivery": {"hour": hour}}, tmp_path)
        assert out == ""

    @pytest.mark.parametrize("lead", [-1, "45", 4.5])
    def test_malformed_lead_minutes(self, tmp_path, lead):
        out, _ = run_gate(
            {**VALID, "delivery": {"hour": "07:00", "lead_minutes": lead}}, tmp_path
        )
        assert "delivery.lead_minutes is not a non-negative integer" in out

    def test_bool_lead_minutes_refused(self, tmp_path):
        # True is 1 in Python; a boolean is not a number of minutes.
        out, _ = run_gate(
            {**VALID, "delivery": {"hour": "07:00", "lead_minutes": True}}, tmp_path
        )
        assert "delivery.lead_minutes is not a non-negative integer" in out

    def test_string_false_is_not_a_boolean(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "printer": {"configured": "false", "name": None}}, tmp_path
        )
        assert "printer.configured is not a boolean" in out

    def test_configured_printer_needs_a_name(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "printer": {"configured": True, "name": "   "}}, tmp_path
        )
        assert "printer.name is blank while printer.configured is true" in out

    def test_null_name_collapses_to_not_valid_json(self, tmp_path):
        # A null name is a shape the checks cannot inspect (non-string where
        # a string is required) -- the same collapse as the ld gate.
        out, _ = run_gate(
            {**VALID, "printer": {"configured": True, "name": None}}, tmp_path
        )
        assert out == "not valid JSON"

    def test_extra_hours_absent_is_valid(self, tmp_path):
        out, _ = run_gate(VALID, tmp_path)
        assert out == ""

    def test_extra_hours_accepts_real_times(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "delivery": {"hour": "03:00", "extra_hours": ["10:30", "16:00"]}},
            tmp_path,
        )
        assert out == ""

    @pytest.mark.parametrize("bad", ["10:30", ["10:75"], ["nope"], [700]])
    def test_extra_hours_rejects_malformed(self, tmp_path, bad):
        config = {**VALID, "delivery": {"hour": "03:00", "extra_hours": bad}}
        out, _ = run_gate(config, tmp_path)
        assert 'delivery.extra_hours is not a list of "HH:MM" strings' in out

    def test_extra_hours_null_is_treated_as_absent(self, tmp_path):
        # Same convention as delivery.lead_minutes: an explicit null reads
        # the same as the key being missing, not as a malformed value.
        out, _ = run_gate(
            {**VALID, "delivery": {"hour": "03:00", "extra_hours": None}}, tmp_path
        )
        assert out == ""

    def test_language_absent_is_valid(self, tmp_path):
        out, _ = run_gate(VALID, tmp_path)
        assert out == ""

    def test_language_accepts_a_plain_name(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "owner": {"timezone": "UTC", "language": "Mandarin Chinese"}},
            tmp_path,
        )
        assert out == ""

    def test_language_blank_refused(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "owner": {"timezone": "UTC", "language": "   "}}, tmp_path
        )
        assert "owner.language is blank" in out

    def test_mail_absent_is_valid(self, tmp_path):
        out, _ = run_gate(VALID, tmp_path)
        assert out == ""

    def test_mail_configured_true_passes(self, tmp_path):
        out, _ = run_gate({**VALID, "mail": {"configured": True}}, tmp_path)
        assert out == ""

    def test_mail_configured_must_be_boolean(self, tmp_path):
        out, _ = run_gate({**VALID, "mail": {"configured": "yes"}}, tmp_path)
        assert "mail.configured is not a boolean" in out

    def test_signals_absent_is_valid(self, tmp_path):
        # An install from before signal sources existed: every source off.
        out, _ = run_gate(VALID, tmp_path)
        assert out == ""

    def test_signals_switches_pass(self, tmp_path):
        signals = {"group_chat": True, "email": False, "imessage": True}
        out, _ = run_gate({**VALID, "signals": signals}, tmp_path)
        assert out == ""

    def test_signals_switch_must_be_boolean(self, tmp_path):
        out, _ = run_gate({**VALID, "signals": {"group_chat": True, "email": "on", "imessage": False}}, tmp_path)
        assert "signals.email is not a boolean" in out

    def test_signals_unknown_source_is_refused(self, tmp_path):
        out, _ = run_gate({**VALID, "signals": {"group_chat": True, "sms": True}}, tmp_path)
        assert "signals.sms is not a signal source" in out

    def test_signals_must_be_an_object(self, tmp_path):
        out, _ = run_gate({**VALID, "signals": ["email"]}, tmp_path)
        assert "signals is not an object" in out

    def test_priority_absent_is_valid(self, tmp_path):
        config = dict(VALID)
        config.pop("priority", None)
        out, _ = run_gate(config, tmp_path)
        assert out == ""

    def test_priority_configured_must_be_boolean(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "priority": {"configured": "true", "file": "~/Plow/prioritization.md"}},
            tmp_path,
        )
        assert out == "priority.configured is not a boolean"

    def test_a_configured_desk_needs_no_path(self, tmp_path):
        out, _ = run_gate({**VALID, "priority": {"configured": True}}, tmp_path)
        assert out == ""

    def test_placeholder_anywhere(self, tmp_path):
        out, _ = run_gate(
            {**VALID, "owner": {"timezone": "[OWNER_TZ]"}}, tmp_path
        )
        assert "an unfilled [UPPER_SNAKE] placeholder remains" in out

    def test_failures_join_with_semicolons(self, tmp_path):
        out, _ = run_gate(
            {"owner": {"timezone": "UTC"}, "delivery": {"hour": "nope"},
             "printer": {"configured": "no"}}, tmp_path
        )
        assert out == ('delivery.hour is not "HH:MM"; '
                       "printer.configured is not a boolean")


class TestExample:
    def test_filled_example_passes(self, tmp_path):
        import pathlib
        from conftest import ROOT

        example = (ROOT / "pt-shared/references/config.example.json").read_text()
        filled = (
            example.replace("[OWNER_TZ]", "America/Los_Angeles")
            .replace("[DELIVERY_HOUR]", "07:00")
        )
        out, _ = run_gate(json.loads(filled), tmp_path)
        assert out == ""

    def test_the_example_itself_carries_placeholders(self, tmp_path):
        import json
        import pathlib
        from conftest import ROOT

        example = json.loads(
            (ROOT / "pt-shared/references/config.example.json").read_text()
        )
        out, _ = run_gate(example, tmp_path)
        assert "placeholder" in out
