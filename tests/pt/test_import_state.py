"""import_state.py -- bringing a paper over from the previous runtime's volume."""
from __future__ import annotations

import json

import pytest

from conftest import load_module

importer = load_module("import_state", "pt-setup/scripts/import_state.py")

CONFIG = {
    "owner": {"timezone": "America/Sao_Paulo", "language": "Português"},
    "delivery": {"hour": "07:00"},
    "printer": {"configured": True, "name": "HP_LaserJet"},
}
TOPICS = {"topics": [
    {"id": "t_9f2a", "text": "IA", "kind": "subscription", "depth": "deep", "status": "pending",
     "created_at": "2026-09-01T07:00:00-03:00", "last_edition_at": None, "scheduled_for": None, "run_on": None},
]}


@pytest.fixture
def old_home(tmp_path):
    pt = tmp_path / "old-home" / "pt"
    pt.mkdir(parents=True)
    (pt / "config.json").write_text(json.dumps(CONFIG))
    (pt / "topics.json").write_text(json.dumps(TOPICS))
    (pt / "run").mkdir()
    (pt / "run" / "paper-workspace-2026-09-01.lock").write_text("x")
    return tmp_path / "old-home"


@pytest.fixture
def pt_home(tmp_path, monkeypatch):
    home = tmp_path / "new-pt"
    monkeypatch.setenv("PT_HOME", str(home))
    return home


def run(argv, calls=None):
    def register(previous_tz):
        if calls is not None:
            calls.append(previous_tz)
        return 0
    return importer.main(argv, register_jobs=register)


@pytest.mark.parametrize("sub", ["", "pt"])
def test_imports_config_and_topics_from_the_home_or_its_pt_dir(old_home, pt_home, sub, capsys):
    source = old_home / sub if sub else old_home
    assert run(["--from", str(source), "--no-register"]) == 0
    assert json.loads((pt_home / "config.json").read_text()) == CONFIG
    assert json.loads((pt_home / "topics.json").read_text()) == TOPICS
    assert not (pt_home / "run").exists(), "scratch and locks stay behind"
    assert "imported:" in capsys.readouterr().out


def test_registers_the_jobs_last_with_the_previous_zone(old_home, pt_home):
    calls = []
    assert run(["--from", str(old_home), "--previous-tz", "America/Sao_Paulo"], calls) == 0
    assert calls == ["America/Sao_Paulo"]


def test_an_existing_paper_is_never_overwritten_by_accident(old_home, pt_home):
    pt_home.mkdir()
    (pt_home / "config.json").write_text('{"mine": true}')
    with pytest.raises(SystemExit, match="already exists"):
        run(["--from", str(old_home), "--no-register"])
    assert (pt_home / "config.json").read_text() == '{"mine": true}'
    assert run(["--from", str(old_home), "--no-register", "--replace"]) == 0
    assert json.loads((pt_home / "config.json").read_text()) == CONFIG


def test_a_config_failing_the_gate_writes_nothing(old_home, pt_home):
    (old_home / "pt" / "config.json").write_text(json.dumps({**CONFIG, "delivery": {"hour": "7am"}}))
    with pytest.raises(SystemExit, match="fails the setup gate"):
        run(["--from", str(old_home)])
    assert not pt_home.exists()


@pytest.mark.parametrize("topics", ['{"nope": []}', '{"topics": [{"text": "no id"}]}', "not json"])
def test_a_topic_store_of_the_wrong_shape_writes_nothing(old_home, pt_home, topics):
    (old_home / "pt" / "topics.json").write_text(topics)
    with pytest.raises(SystemExit, match="refusing to import"):
        run(["--from", str(old_home)])
    assert not pt_home.exists()


def test_no_topic_store_imports_an_empty_one(old_home, pt_home):
    (old_home / "pt" / "topics.json").unlink()
    assert run(["--from", str(old_home), "--no-register"]) == 0
    assert json.loads((pt_home / "topics.json").read_text()) == {"topics": []}


def test_a_directory_without_a_paper_is_refused(tmp_path, pt_home):
    with pytest.raises(SystemExit, match="no pt/config.json"):
        run(["--from", str(tmp_path)])
