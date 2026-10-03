"""run_attempts.py -- a paper that keeps failing stops re-running all day."""
from __future__ import annotations

import contextlib
import io

import pytest

from conftest import load_module

attempts = load_module("run_attempts", "pt-shared/scripts/run_attempts.py")


@pytest.fixture
def pt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))
    return tmp_path / "pt"


def begin():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = attempts.main(["begin"])
    assert code == 0
    return buf.getvalue().strip()


def test_the_first_attempts_proceed(pt_home):
    assert [begin() for _ in range(attempts.MAX_ATTEMPTS)] == ["proceed"] * attempts.MAX_ATTEMPTS


def test_the_next_one_gives_up_and_only_the_first_give_up_asks_for_a_notice(pt_home):
    for _ in range(attempts.MAX_ATTEMPTS):
        begin()
    assert [begin(), begin(), begin()] == ["give-up", "give-up-quiet", "give-up-quiet"]


def test_a_confirmed_delivery_starts_the_day_over(pt_home):
    for _ in range(attempts.MAX_ATTEMPTS):
        begin()
    attempts.clear()
    assert begin() == "proceed"


def test_clearing_without_a_count_is_not_an_error(pt_home):
    attempts.clear()


def test_the_count_is_the_owner_days(pt_home, monkeypatch):
    for _ in range(attempts.MAX_ATTEMPTS):
        begin()
    from datetime import date
    monkeypatch.setattr(attempts, "owner_today", lambda: date(2030, 1, 1))
    assert begin() == "proceed"
