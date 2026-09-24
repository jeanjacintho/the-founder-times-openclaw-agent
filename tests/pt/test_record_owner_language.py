"""record_owner_language.py — keep owner.language matching this turn."""
from __future__ import annotations

import json
import stat

from conftest import ROOT, load_module

rec = load_module("record_owner_language", "pt-shared/scripts/record_owner_language.py")

READY = {
    "owner": {"timezone": "America/Sao_Paulo", "language": "Portuguese"},
    "delivery": {"hour": "07:00"},
    "printer": {"configured": False, "name": None},
}


def test_script_is_executable():
    path = ROOT / "pt-shared" / "scripts" / "record_owner_language.py"
    assert path.stat().st_mode & stat.S_IXUSR


def test_ready_config_switches_language(tmp_path, capsys):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(READY), encoding="utf-8")
    rc = rec.main(["record_owner_language.py", str(config), "English"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "LANG:English"
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["owner"]["language"] == "English"
    assert data["owner"]["timezone"] == "America/Sao_Paulo"


def test_same_language_is_a_noop(tmp_path, capsys):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(READY), encoding="utf-8")
    before = config.read_text(encoding="utf-8")
    rc = rec.main(["record_owner_language.py", str(config), "Portuguese"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "LANG:Portuguese"
    assert config.read_text(encoding="utf-8") == before


def test_setup_needed_writes_the_draft_not_a_half_config(tmp_path, capsys):
    config = tmp_path / "config.json"
    rc = rec.main(["record_owner_language.py", str(config), "English"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "LANG:English"
    assert not config.exists()
    draft = json.loads((tmp_path / ".setup-draft.json").read_text(encoding="utf-8"))
    assert draft["owner"]["language"] == "English"


def test_blank_language_is_refused(tmp_path, capsys):
    config = tmp_path / "config.json"
    config.write_text(json.dumps(READY), encoding="utf-8")
    rc = rec.main(["record_owner_language.py", str(config), "  "])
    assert rc == 1
    assert "language" in capsys.readouterr().err.lower()
    assert json.loads(config.read_text())["owner"]["language"] == "Portuguese"


def test_usage_without_args(capsys):
    rc = rec.main(["record_owner_language.py"])
    assert rc == 1
    assert "usage" in capsys.readouterr().err


def test_a_language_with_no_phrases_asks_for_them(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    config = tmp_path / "config.json"
    config.write_text(json.dumps(READY), encoding="utf-8")
    assert rec.main(["record_owner_language.py", str(config), "Mandarin Chinese"]) == 0
    assert capsys.readouterr().out.strip().splitlines() == ["LANG:Mandarin Chinese", "PHRASES:missing"]


def test_curated_languages_never_ask_for_phrases(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    config = tmp_path / "config.json"
    config.write_text(json.dumps(READY), encoding="utf-8")
    for language in ("English", "Português", "pt-BR"):
        rec.main(["record_owner_language.py", str(config), language])
        assert capsys.readouterr().out.strip() == f"LANG:{language}"
