"""setup_needed.py — first-run gate for live chat."""
from __future__ import annotations

import json

from conftest import load_module

needed = load_module("setup_needed", "pt-shared/scripts/setup_needed.py")

VALID = {
    "owner": {"timezone": "America/Sao_Paulo"},
    "delivery": {"hour": "07:00"},
    "printer": {"configured": False, "name": None},
}


class TestSetupNeeded:
    def test_missing_file_is_needed(self, tmp_path):
        assert needed.setup_needed(tmp_path / "absent.json") is True

    def test_garbage_is_needed(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("nope")
        assert needed.setup_needed(path) is True

    def test_valid_is_ready(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps(VALID))
        assert needed.setup_needed(path) is False

    def test_missing_timezone_is_needed(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({**VALID, "owner": {}}))
        assert needed.setup_needed(path) is True

    def test_printer_false_is_ready(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text(json.dumps(VALID))
        assert needed.setup_needed(path) is False

    def test_cli_prints_setup_needed(self, tmp_path, capsys):
        needed.main(["setup_needed.py", str(tmp_path / "missing.json")])
        assert capsys.readouterr().out.strip() == "SETUP_NEEDED\nDRAFT:none\nLANG:unrecorded"

    def test_cli_prints_draft_hour_when_present(self, tmp_path, capsys):
        config = tmp_path / "config.json"
        (tmp_path / ".setup-draft.json").write_text(json.dumps({"local_hour": "07:00"}))
        needed.main(["setup_needed.py", str(config)])
        assert capsys.readouterr().out.strip() == "SETUP_NEEDED\nDRAFT:local_hour\nLANG:unrecorded"

    def test_cli_prints_ready(self, tmp_path, capsys):
        path = tmp_path / "config.json"
        path.write_text(json.dumps(VALID))
        needed.main(["setup_needed.py", str(path)])
        assert capsys.readouterr().out.strip() == "READY\nLANG:unrecorded"


class TestLanguageLine:
    """The owner's language is a FACT the gate hands back every turn, not a
    rule the model has to remember while composing.

    Measured live, four times now: an owner wrote a whole setup interview in
    English and a reply came back in another language -- three times on a
    failure explanation (SOUL.md records those), and once on the printer
    SUCCESS branch, in Dutch. The three failure branches had a prose reminder
    attached; the success branch did not. Enumerating branches is losing.
    This gate already runs as the first action of every single reply, so the
    recorded language rides back on every one of them.
    """

    def write(self, tmp_path, draft):
        import json

        (tmp_path / ".setup-draft.json").write_text(json.dumps(draft), encoding="utf-8")
        return tmp_path / "config.json"

    def test_language_line_reports_the_recorded_language(self, tmp_path):
        config = self.write(tmp_path, {"local_hour": "07:00", "owner": {"language": "English"}})
        assert needed.language_line(config) == "LANG:English"

    def test_language_line_says_unrecorded_when_absent(self, tmp_path):
        config = self.write(tmp_path, {"local_hour": "07:00"})
        assert needed.language_line(config) == "LANG:unrecorded"

    def test_language_line_with_no_draft_at_all(self, tmp_path):
        assert needed.language_line(tmp_path / "config.json") == "LANG:unrecorded"

    def test_blank_language_is_unrecorded(self, tmp_path):
        config = self.write(tmp_path, {"owner": {"language": "   "}})
        assert needed.language_line(config) == "LANG:unrecorded"

    def test_main_prints_the_language_line_on_every_unfinished_reply(self, tmp_path, capsys):
        config = self.write(tmp_path, {"local_hour": "07:00", "owner": {"language": "Portuguese"}})
        needed.main(["needed.py", str(config)])
        lines = capsys.readouterr().out.splitlines()
        assert lines[0] == "SETUP_NEEDED"
        assert lines[1].startswith("DRAFT:")
        assert lines[2] == "LANG:Portuguese"

    def test_language_line_falls_back_to_config_when_draft_has_none(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({
            **VALID,
            "owner": {**VALID["owner"], "language": "Portuguese"},
        }), encoding="utf-8")
        assert needed.language_line(config) == "LANG:Portuguese"

    def test_draft_language_wins_over_config_during_setup(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({
            **VALID,
            "owner": {**VALID["owner"], "language": "English"},
        }), encoding="utf-8")
        (tmp_path / ".setup-draft.json").write_text(
            json.dumps({"owner": {"language": "Portuguese"}}), encoding="utf-8"
        )
        assert needed.language_line(config) == "LANG:Portuguese"

    def test_cli_prints_lang_on_ready(self, tmp_path, capsys):
        path = tmp_path / "config.json"
        path.write_text(json.dumps({
            **VALID,
            "owner": {**VALID["owner"], "language": "English"},
        }), encoding="utf-8")
        needed.main(["setup_needed.py", str(path)])
        assert capsys.readouterr().out.strip() == "READY\nLANG:English"

    def test_draft_line_format_is_unchanged(self, tmp_path):
        # The LANG line is additive: DRAFT: keeps its exact old contract.
        config = self.write(tmp_path, {"local_hour": "07:00", "owner": {"language": "English"}})
        assert needed.draft_line(config) == "DRAFT:local_hour"
