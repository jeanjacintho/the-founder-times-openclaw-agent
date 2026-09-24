"""prepare_daily_run.py gives each daily paper an empty scratch workspace."""
from datetime import datetime, timezone

from conftest import load_module

prepare = load_module("prepare_daily_run", "pt-shared/scripts/prepare_daily_run.py")
NOW = datetime(2026, 9, 20, 11, 7, 10, tzinfo=timezone.utc)


def test_archives_only_prior_run_scratch_and_keeps_the_live_lock(tmp_path):
    run = tmp_path / "run"
    for name in ("desk-priority", "desk-weather", "t_4cac", "2026-09-20",
                 "daily-2026-09-20", "daily2-2026-09-20"):
        path = run / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "notes.json").write_text(name)
    for name in ("chat-status.json", "seal-session.json"):
        (run / name).write_text(name)
    (run / "daily-2026-09-20.lock").write_text("held")
    (run / "company-set-dm.json").write_text("durable setup evidence")

    archived = prepare.prepare(tmp_path, NOW)

    assert archived == tmp_path.parent / f".{tmp_path.name}-run-archives" / "run-20260920-110710"
    for name in ("desk-priority", "desk-weather", "2026-09-20",
                 "daily-2026-09-20", "daily2-2026-09-20",
                 "chat-status.json", "seal-session.json"):
        assert (archived / name).exists()
        assert not (run / name).exists()
    assert (run / "t_4cac" / "notes.json").read_text() == "t_4cac"
    assert (run / "daily-2026-09-20.lock").read_text() == "held"
    assert (run / "company-set-dm.json").read_text() == "durable setup evidence"


def test_nothing_to_archive_is_a_noop(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "daily-2026-09-20.lock").write_text("held")
    assert prepare.prepare(tmp_path, NOW) is None
    assert sorted(p.name for p in run.iterdir()) == ["daily-2026-09-20.lock"]


def test_same_second_uses_a_distinct_recoverable_archive(tmp_path):
    run = tmp_path / "run"
    (run / "desk-priority").mkdir(parents=True)
    archive_root = tmp_path.parent / f".{tmp_path.name}-run-archives"
    archive_root.mkdir()
    (archive_root / "run-20260920-110710").mkdir()
    archived = prepare.prepare(tmp_path, NOW)
    assert archived == archive_root / "run-20260920-110710-2"


def test_noncanonical_paper_keeps_only_priority_desk(tmp_path):
    run = tmp_path / "run"
    for name in ("desk-priority", "desk-weather", "desk-mail"):
        (run / name).mkdir(parents=True, exist_ok=True)
    archived = prepare.prepare(tmp_path, NOW, preserve_priority=True)
    assert (run / "desk-priority").exists()
    assert not (run / "desk-weather").exists()
    assert not (run / "desk-mail").exists()
    assert (archived / "desk-weather").exists()
    assert (archived / "desk-mail").exists()


def test_cli_does_not_reveal_the_archive_to_the_research_agent():
    source = prepare.Path(prepare.__file__).read_text()
    assert 'print("READY")' in source
    assert "ARCHIVED" not in source
