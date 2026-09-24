"""owner_time.py: the owner's own clock, from pt/config.json, not the container's."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from conftest import load_module

owner_time = load_module("owner_time", "pt-shared/scripts/owner_time.py")


class TestOwnerNow:
    def test_the_owners_zone_can_land_a_day_off_the_containers(self, tmp_path, monkeypatch):
        # 23:30 UTC: the container (UTC) is still on the 19th; the owner in
        # Kiritimati (UTC+14) is already on the 20th.
        instant = datetime(2026, 9, 19, 23, 30, tzinfo=timezone.utc)

        class FixedDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant.astimezone(tz) if tz else instant

        monkeypatch.setattr(owner_time, "datetime", FixedDatetime)
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"owner": {"timezone": "Pacific/Kiritimati"}}))
        assert instant.date() == date(2026, 9, 19)  # the container's own day
        assert owner_time.owner_today(config) == date(2026, 9, 20)

    def test_a_missing_config_falls_back_to_the_container_clock(self, tmp_path):
        assert owner_time.owner_today(tmp_path / "nope.json") == date.today()

    def test_the_default_config_path_follows_pt_home(self, tmp_path, monkeypatch):
        # Same override every other pt script honors (topics.py, run_lock.py,
        # record_edition.py) -- tests point it at a tmp dir; CONFIG must read
        # it at call time, not bake in whatever it was at import.
        monkeypatch.setenv("PT_HOME", str(tmp_path))
        (tmp_path / "config.json").write_text(
            json.dumps({"owner": {"timezone": "America/Sao_Paulo"}}))
        assert str(owner_time.owner_now().tzinfo) == "America/Sao_Paulo"

    def test_an_unknown_timezone_name_refuses_instead_of_guessing(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"owner": {"timezone": "Not/AZone"}}))
        with pytest.raises(KeyError):
            owner_time.owner_now(config)
