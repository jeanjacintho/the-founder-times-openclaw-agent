"""advice_unavailable.py: the advice desk may print "unavailable" only with proof."""
from __future__ import annotations

import json

import pytest

from conftest import load_module

adv = load_module("advice_unavailable", "pt-priority/scripts/advice_unavailable.py")

DAY = "2026-09-30"
TZ = "America/Sao_Paulo"
LOCK = "2026-09-30T07:00:14-03:00"


@pytest.fixture
def home(tmp_path, monkeypatch):
    """PT_HOME with the owner's config and a lock this paper took at 07:00:14."""
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({"owner": {"timezone": TZ}}))
    run = tmp_path / "run"
    run.mkdir()
    (run / f"paper-workspace-{DAY}.lock").write_text(LOCK + "\n")
    monkeypatch.setattr(adv, "today", lambda: DAY)
    return tmp_path


def notes(home):
    return json.loads((home / "run" / "desk-priority" / "notes.json").read_text())


class TestWindow:
    # Measured live 2026-09-30: the 07:00 paper had 148 minutes to 09:30 and
    # printed "advice unavailable" without starting a single critic.
    def test_a_morning_paper_with_its_full_window_may_not_skip(self, home, capsys):
        with pytest.raises(SystemExit) as exc:
            adv.main(["window", "--deliver-at", "09:30", "--reason", "sem tempo"])
        assert "149 minutes" in str(exc.value) and "run the tournament" in str(exc.value)
        assert not (home / "run" / "desk-priority" / "notes.json").exists()

    def test_a_paper_that_took_the_lock_after_its_hour_records_why(self, home):
        (home / "run" / f"paper-workspace-{DAY}.lock").write_text("2026-09-30T13:13:00-03:00\n")
        adv.main(["window", "--deliver-at", "09:30", "--reason", "a entrega já tinha passado"])
        assert notes(home) == {
            "date": DAY, "could_not_source": ["a entrega já tinha passado"],
            "skip": {"kind": "window", "deliver_at": "09:30", "lock": "2026-09-30T13:13:00-03:00"}}

    def test_without_the_lock_there_is_no_window_to_measure(self, home):
        (home / "run" / f"paper-workspace-{DAY}.lock").unlink()
        with pytest.raises(SystemExit, match="does not hold today's paper-workspace lock"):
            adv.main(["window", "--deliver-at", "09:30", "--reason", "x"])

    def test_a_tournament_that_ran_has_no_failed_reason(self, home):
        with pytest.raises(SystemExit):
            adv.main(["failed", "--reason", "a terceira geração não passou no gate"])


class TestBlocked:
    def test_a_reachable_wiki_is_not_a_blocked_desk(self, home, monkeypatch):
        monkeypatch.setattr(adv, "wiki_check", lambda: (0, "WIKI:ready"))
        with pytest.raises(SystemExit, match="wiki_setup.py --desk succeeded"):
            adv.main(["blocked", "--reason", "o wiki não respondeu"])

    def test_an_unreachable_wiki_records_the_check_that_failed(self, home, monkeypatch):
        monkeypatch.setattr(adv, "wiki_check", lambda: (1, "error: wiki not ready — Mac unreachable"))
        adv.main(["blocked", "--reason", "o Mac não respondeu"])
        assert notes(home)["skip"] == {"kind": "blocked", "lock": LOCK,
                                       "check": "error: wiki not ready — Mac unreachable"}


# What render_edition.py re-checks before printing an unavailable card. The
# 13:13 lock is a later paper's: desk-priority survives its --preserve-priority,
# so a reason the 07:00 paper proved must not print in it.
@pytest.mark.parametrize(("skip", "lock", "expected", "wiki"), [
    (None, LOCK, "not written by advice_unavailable.py", 1),
    ({"kind": "window", "deliver_at": "09:30", "lock": LOCK}, LOCK, "149 minutes", 1),
    ({"kind": "window", "deliver_at": "09:30", "lock": "2026-09-30T09:00:00-03:00"},
     "2026-09-30T13:13:00-03:00", "another paper's lock", 1),
    ({"kind": "window", "deliver_at": "09:30"}, LOCK, "another paper's lock", 1),
    ({"kind": "blocked", "check": "error: Mac unreachable", "lock": LOCK}, LOCK, None, 1),
    ({"kind": "blocked", "check": "error: Mac unreachable", "lock": LOCK}, LOCK,
     "succeeds now", 0),
    ({"kind": "blocked", "check": "", "lock": LOCK}, LOCK, "no failed check", 1),
    ({"kind": "failed", "lock": LOCK}, LOCK, "not written by advice_unavailable.py", 1),
])
def test_proof_matrix(home, skip, lock, expected, wiki):
    (home / "run" / f"paper-workspace-{DAY}.lock").write_text(lock + "\n")
    problem = adv.proof_problem({"skip": skip} if skip else {}, home / "run", DAY, TZ,
                                lambda: (wiki, "error: Mac unreachable"))
    assert expected in problem if expected else problem is None
