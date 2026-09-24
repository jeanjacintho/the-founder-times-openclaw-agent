"""history.py: what the advisor's desk printed lately, read back from the wiki."""
from __future__ import annotations

import json
from datetime import date

import pytest

from conftest import load_module
from wiki import EDITIONS, Wiki, join_page

history = load_module("history", "pt-priority/scripts/history.py")
TODAY = date(2026, 9, 19)


def day_page(mac, day, card=None, sections=None):
    path = mac.home / "Plow" / "wiki" / EDITIONS / f"{day}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"type": "Edition", "date": day,
            **({"priority": card} if card else {}),
            **({"sections": sections} if sections else {})}
    path.write_text(join_page(meta, f"# The Founder Times, {day}\n"))


class TestRecent:
    def test_the_last_weeks_cards_oldest_first_without_the_empty_days(self, mac):
        day_page(mac, "2026-09-11", {"headline": "too old"})
        day_page(mac, "2026-09-12", {"headline": "Call Raj"})
        day_page(mac, "2026-09-15")  # an edition without the desk
        day_page(mac, "2026-09-18", {"headline": "Close the pilot"})
        assert history.recent(Wiki(mac.call_tool), TODAY) == [
            {"date": "2026-09-12", "desk": {"headline": "Call Raj"}},
            {"date": "2026-09-18", "desk": {"headline": "Close the pilot"}},
        ]

    def test_todays_own_edition_is_not_history(self, mac):
        # A second run on the same date must not read the first back as "yesterday".
        day_page(mac, "2026-09-18", {"headline": "Close the pilot"})
        day_page(mac, "2026-09-19", {"headline": "This morning's headline"})
        assert history.recent(Wiki(mac.call_tool), TODAY) == [
            {"date": "2026-09-18", "desk": {"headline": "Close the pilot"}},
        ]

    def test_only_todays_edition_is_no_history(self, mac):
        day_page(mac, "2026-09-19", {"headline": "This morning's headline"})
        assert history.recent(Wiki(mac.call_tool), TODAY) == []

    def test_no_pages_is_no_history(self, mac):
        assert history.recent(Wiki(mac.call_tool), TODAY) == []


class TestRecentTopic:
    def test_what_this_section_printed_oldest_first_with_its_sources(self, mac):
        day_page(mac, "2026-09-17", sections={"t_9f2a": {
            "headline": "Apple approved Poke",
            "printed": [{"claim": "Poke went live in June", "url": "https://tc.example/poke"}]}})
        day_page(mac, "2026-09-18", sections={
            # A focused paper and the daily one both carried the section; record_edition.py
            # merges them into one frontmatter entry before history.py ever reads it -- the
            # later edition's headline wins, and its claims accumulate onto the earlier's.
            "t_9f2a": {"headline": "Cognition bought Poke",
                       "printed": [{"claim": "Apple approved the deal that morning", "url": "https://tc.example/apple"},
                                   {"claim": "Low nine figures", "url": "https://tc.example/cognition"}]},
            "t_0001": {"headline": "Another section",
                       "printed": [{"claim": "Unrelated", "url": "https://other.example"}]}})
        assert history.recent(Wiki(mac.call_tool), TODAY, topic="t_9f2a") == [
            {"date": "2026-09-17", "headline": "Apple approved Poke",
             "printed": [{"claim": "Poke went live in June", "url": "https://tc.example/poke"}]},
            {"date": "2026-09-18", "headline": "Cognition bought Poke",
             "printed": [{"claim": "Apple approved the deal that morning", "url": "https://tc.example/apple"},
                         {"claim": "Low nine figures", "url": "https://tc.example/cognition"}]},
        ]

    def test_todays_edition_is_in_topic_history_for_a_second_paper_the_same_day(self, mac):
        # An afternoon focused paper or a live copy is the most likely thing
        # to reprint this morning's section -- exactly what this history
        # exists to stop -- so unlike the desk's, the topic window reaches
        # through today's own page.
        day_page(mac, "2026-09-19", sections={"t_9f2a": {
            "headline": "This morning's headline",
            "printed": [{"claim": "This morning's claim", "url": "https://a.example"}]}})
        assert history.recent(Wiki(mac.call_tool), TODAY, topic="t_9f2a") == [
            {"date": "2026-09-19", "headline": "This morning's headline",
             "printed": [{"claim": "This morning's claim", "url": "https://a.example"}]},
        ]

    def test_a_day_that_did_not_print_this_section_is_left_out(self, mac):
        day_page(mac, "2026-09-17", {"headline": "Close the pilot"})
        day_page(mac, "2026-09-18", sections={"t_0001": {"headline": "Another section", "printed": []}})
        assert history.recent(Wiki(mac.call_tool), TODAY, topic="t_9f2a") == []

    def test_the_desks_own_history_is_unchanged(self, mac):
        # The priority desk's reader must not notice this flag exists.
        day_page(mac, "2026-09-18", {"headline": "Close the pilot"},
                 sections={"t_9f2a": {"headline": "The dollar",
                                       "printed": [{"claim": "BRL up", "url": "https://fx.example"}]}})
        assert history.recent(Wiki(mac.call_tool), TODAY) == [
            {"date": "2026-09-18", "desk": {"headline": "Close the pilot"}},
        ]


class TestCli:
    def test_an_unreachable_mac_is_an_error(self, mac, monkeypatch):
        mac.asleep = True
        monkeypatch.setattr(history, "connect", lambda: Wiki(mac.call_tool))
        with pytest.raises(SystemExit) as exc:
            history.main(["recent"])
        assert str(exc.value).startswith("error: history unavailable — Mac unreachable")

    def test_a_bad_owner_timezone_is_an_error(self, mac, monkeypatch):
        # owner_time.owner_today()'s own refuse-instead-of-guess behavior is
        # tested in test_owner_time.py; this just proves main() surfaces
        # whatever it raises as the documented error, not a bare traceback.
        monkeypatch.setattr(history, "connect", lambda: Wiki(mac.call_tool))

        def bad_owner_today():
            raise KeyError("Not/AZone")

        monkeypatch.setattr(history, "owner_today", bad_owner_today)
        with pytest.raises(SystemExit) as exc:
            history.main(["recent"])
        assert str(exc.value).startswith("error: history unavailable — ")

    def test_the_topic_flag_prints_that_sections_blocks(self, mac, monkeypatch, capsys):
        day_page(mac, "2026-09-18", sections={"t_9f2a": {
            "headline": "Cognition bought Poke",
            "printed": [{"claim": "Low nine figures", "url": "https://tc.example/x"}]}})
        monkeypatch.setattr(history, "connect", lambda: Wiki(mac.call_tool))
        monkeypatch.setattr(history, "owner_today", lambda: TODAY)
        history.main(["recent", "--topic", "t_9f2a"])
        assert json.loads(capsys.readouterr().out) == [
            {"date": "2026-09-18", "headline": "Cognition bought Poke",
             "printed": [{"claim": "Low nine figures", "url": "https://tc.example/x"}]},
        ]
