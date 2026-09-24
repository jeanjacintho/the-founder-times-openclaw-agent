from pathlib import Path

from conftest import load_module

paths = load_module("pt_paths", "pt-shared/scripts/pt_paths.py")


def test_defaults_are_the_image_paths(monkeypatch):
    monkeypatch.delenv("PT_HOME", raising=False)
    monkeypatch.delenv("PT_SKILLS", raising=False)
    assert paths.pt_home() == Path("/var/lib/plow/pt")
    assert paths.config_file() == Path("/var/lib/plow/pt/config.json")
    assert paths.skills() == Path("/opt/plow/skills")
    assert paths.script("pt-shared", "run_lock.py") == Path("/opt/plow/skills/pt-shared/scripts/run_lock.py")


def test_env_overrides_are_read_at_call_time(monkeypatch, tmp_path):
    monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))
    monkeypatch.setenv("PT_SKILLS", str(tmp_path / "skills"))
    assert paths.config_file() == tmp_path / "pt" / "config.json"
    assert paths.script("pt-intake", "topics.py") == tmp_path / "skills" / "pt-intake" / "scripts" / "topics.py"


def test_blank_override_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("PT_HOME", "")
    assert paths.pt_home() == Path("/var/lib/plow/pt")
