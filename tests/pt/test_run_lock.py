"""run_lock.py -- one owner per run name, with stale takeover."""
from __future__ import annotations

import contextlib
import io
from datetime import datetime, timedelta, timezone

import pytest

from conftest import load_module

lock = load_module("run_lock", "pt-shared/scripts/run_lock.py")


@pytest.fixture
def pt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))
    return tmp_path / "pt"


def out(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = lock.main(argv)
    return code, buf.getvalue().strip()


def test_first_acquire_wins(pt_home):
    code, text = out(["acquire", "--name", "daily-2026-09-11"])
    assert code == 0 and text == "acquired"
    assert (pt_home / "run" / "daily-2026-09-11.lock").is_file()


def test_second_acquire_is_held(pt_home):
    out(["acquire", "--name", "daily-2026-09-11"])
    code, text = out(["acquire", "--name", "daily-2026-09-11"])
    assert code == 0 and text == "held"


def test_stale_lock_is_taken_over(pt_home):
    out(["acquire", "--name", "daily-2026-09-11"])
    lock_path = pt_home / "run" / "daily-2026-09-11.lock"
    old = (datetime.now(timezone.utc).astimezone() - timedelta(minutes=500))
    lock_path.write_text(old.isoformat(timespec="seconds") + "\n")
    code, text = out(["acquire", "--name", "daily-2026-09-11"])
    assert code == 0 and text == "stale-takeover"


def test_unparseable_lock_is_taken_over(pt_home):
    lock_path = pt_home / "run" / "daily-2026-09-11.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("garbage")
    _, text = out(["acquire", "--name", "daily-2026-09-11"])
    assert text == "stale-takeover"


def test_release_then_acquire(pt_home):
    out(["acquire", "--name", "daily-2026-09-11"])
    assert out(["release", "--name", "daily-2026-09-11"]) == (0, "released")
    assert out(["acquire", "--name", "daily-2026-09-11"]) == (0, "acquired")


def test_release_missing_is_not_an_error(pt_home):
    assert out(["release", "--name", "daily-2026-09-11"]) == (0, "nothing-to-release")


def test_names_with_path_characters_refused(pt_home):
    with pytest.raises(SystemExit, match="not allowed"):
        lock.main(["acquire", "--name", "../escape"])
