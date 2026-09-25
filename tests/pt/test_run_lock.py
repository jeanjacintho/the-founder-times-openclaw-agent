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


def test_simultaneous_fires_elect_exactly_one_paper(pt_home):
    # A scheduled fire and a manual `openclaw cron run` start separate
    # processes at the same moment; exactly one may own the workspace.
    import subprocess
    import sys

    from conftest import ROOT

    script = ROOT / "pt-shared" / "scripts" / "run_lock.py"
    argv = [sys.executable, str(script), "acquire", "--name", "paper-workspace-2026-09-24",
            "--stale-minutes", "240"]
    for round_ in range(10):
        (pt_home / "run" / "paper-workspace-2026-09-24.lock").unlink(missing_ok=True)
        procs = [subprocess.Popen(argv, stdout=subprocess.PIPE, text=True) for _ in range(8)]
        results = sorted(p.communicate()[0].strip() for p in procs)
        assert results == ["acquired"] + ["held"] * 7, f"round {round_}: {results}"


class FakeClock:
    """time.monotonic/time.sleep for the waiting acquire: one tick per sleep."""

    def __init__(self, on_sleep=None):
        self.now = 0.0
        self.sleeps = 0
        self.on_sleep = on_sleep

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        self.sleeps += 1
        if self.on_sleep:
            self.on_sleep(self)


def use_clock(monkeypatch, clock):
    monkeypatch.setattr(lock.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(lock.time, "sleep", clock.sleep)


def test_no_wait_is_the_old_answer(pt_home, monkeypatch):
    clock = FakeClock()
    use_clock(monkeypatch, clock)
    out(["acquire", "--name", "paper-workspace-2026-09-24"])
    assert out(["acquire", "--name", "paper-workspace-2026-09-24"]) == (0, "held")
    assert clock.sleeps == 0


def test_waiting_acquires_once_the_holder_releases(pt_home, monkeypatch):
    out(["acquire", "--name", "paper-workspace-2026-09-24"])
    released = lambda c: c.sleeps == 5 and out(["release", "--name", "paper-workspace-2026-09-24"])
    clock = FakeClock(on_sleep=released)
    use_clock(monkeypatch, clock)
    assert out(["acquire", "--name", "paper-workspace-2026-09-24", "--wait-seconds", "1200"]) == (0, "acquired")
    assert clock.sleeps == 5


def test_waiting_gives_up_as_held_when_the_budget_runs_out(pt_home, monkeypatch):
    out(["acquire", "--name", "paper-workspace-2026-09-24"])
    clock = FakeClock()
    use_clock(monkeypatch, clock)
    assert out(["acquire", "--name", "paper-workspace-2026-09-24", "--wait-seconds", "30"]) == (0, "held")
    assert 29 <= clock.now <= 31


def test_a_lock_that_goes_stale_mid_wait_is_taken_over(pt_home, monkeypatch):
    out(["acquire", "--name", "paper-workspace-2026-09-24"])
    path = pt_home / "run" / "paper-workspace-2026-09-24.lock"

    def age(c):
        if c.sleeps == 3:  # the holder died: its stamp is now older than the stale limit
            path.write_text((datetime.now(timezone.utc) - timedelta(minutes=300)).isoformat() + "\n")
    clock = FakeClock(on_sleep=age)
    use_clock(monkeypatch, clock)
    code, text = out(["acquire", "--name", "paper-workspace-2026-09-24", "--stale-minutes", "240", "--wait-seconds", "1200"])
    assert (code, text) == (0, "stale-takeover")
    assert clock.sleeps == 3


def test_negative_wait_is_refused(pt_home):
    with pytest.raises(SystemExit):
        out(["acquire", "--name", "paper-workspace-2026-09-24", "--wait-seconds", "-1"])


def test_today_names_the_lock_for_the_owners_day(pt_home, monkeypatch):
    # The owner's day, not the container's: 23:30 UTC is already the 25th in Kiritimati.
    pt_home.mkdir(parents=True, exist_ok=True)
    (pt_home / "config.json").write_text('{"owner": {"timezone": "Pacific/Kiritimati"}}')
    monkeypatch.setattr(lock, "owner_today", lambda: __import__("datetime").date(2026, 9, 25))
    assert out(["acquire", "--name", "paper-workspace", "--today"]) == (0, "acquired")
    assert (pt_home / "run" / "paper-workspace-2026-09-25.lock").is_file()
    assert out(["acquire", "--name", "paper-workspace", "--today"]) == (0, "held")
    assert out(["release", "--name", "paper-workspace", "--today"]) == (0, "released")
    assert not (pt_home / "run" / "paper-workspace-2026-09-25.lock").exists()


def test_today_uses_the_real_owner_clock(pt_home):
    pt_home.mkdir(parents=True, exist_ok=True)
    (pt_home / "config.json").write_text('{"owner": {"timezone": "UTC"}}')
    from datetime import datetime, timezone
    out(["acquire", "--name", "paper-workspace", "--today"])
    assert (pt_home / "run" / f"paper-workspace-{datetime.now(timezone.utc).date().isoformat()}.lock").is_file()
