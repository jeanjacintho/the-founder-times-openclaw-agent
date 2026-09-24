"""record_edition.py: a delivered edition becomes the day's page in the owner's wiki."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from conftest import load_module
from wiki import EDITIONS, OVERVIEW, Wiki, split_page

rec = load_module("record_edition", "pt-edition/scripts/record_edition.py")
SP = timezone(timedelta(hours=-3))
MORNING = datetime(2026, 9, 19, 6, 4, tzinfo=SP)
AFTERNOON = datetime(2026, 9, 19, 14, 0, tzinfo=SP)
RECOMMENDATION = {
    "headline": "Close the Acme pilot",
    "body": "The pilot is the shortest path to evidence that changes the next financing decision.",
    "evidence": [{"claim": "Acme asked for pilot terms", "source": "Gmail",
                  "url": "https://example.com/acme"}],
    "first_step": "Send Raj the pilot terms",
    "advisor": {"name": "Patrick Salyer", "quote": "Proof beats promises.",
                "url": "https://example.com/blueprint"},
}
CARD = {"recommendations": [
    RECOMMENDATION,
    {**RECOMMENDATION, "headline": "Confirm the runway model"},
    {**RECOMMENDATION, "headline": "Ask a customer for a reference"},
], "questions": ["Q1 — Which customer would publicly vouch for you?"]}


@pytest.fixture(autouse=True)
def pt_home(monkeypatch, tmp_path):
    """record()'s cross-run lock file lives under PT_HOME; keep it in tmp_path."""
    monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))


def edition(tmp_path, headline="Close the Acme pilot", card=True, news=True,
            news_headline="The real firms", notes=None):
    sections = [
        {"kind": "section", "desk": "weather", "title": "Weather", "headline": "Rain",
         "body": "Rain in Sao Paulo.", "sources": ["https://weather.example"]},
        {"kind": "section", "desk": "mail", "topic_id": "t_1234", "title": "Letters",
         "headline": "Three messages", "body": "Ana Costa — partnership proposal.",
         "sources": ["Gmail"]},
    ]
    if card:
        sections.append({"kind": "section", "desk": "priority", "headline": headline, "priority": CARD})
    if news:
        sections.append({"kind": "section", "topic_id": "t_9f2a", "desk": "news", "title": "The dollar",
                         "headline": news_headline, "body": "The real rose 1%.",
                         "sources": ["https://news.example/fx"]})
        notes_dir = tmp_path / "run" / "t_9f2a"
        notes_dir.mkdir(parents=True, exist_ok=True)
        (notes_dir / "notes.json").write_text(json.dumps({
            "topic_id": "t_9f2a",
            "notes": notes if notes is not None else
                     [{"claim": "BRL up 1% on Sep 18", "url": "https://news.example/fx", "quote": "…"}],
            "could_not_source": ["the central bank's comment"]}))
    run_dir = tmp_path / "run" / "daily-2026-09-19"
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "edition.json"
    path.write_text(json.dumps({"date": "2026-09-19", "location": "Sao Paulo", "sections": sections}))
    return path


def day(mac):
    return (mac.home / "Plow" / "wiki" / EDITIONS / "2026-09-19.md").read_text()


class TestIsLatestEdition:
    @pytest.mark.parametrize(("prior_at", "now", "expected"), [
        (None, MORNING, True),  # no prior card: nothing to lose to
        (MORNING.isoformat(timespec="seconds"), AFTERNOON, True),  # a later time wins
        (AFTERNOON.isoformat(timespec="seconds"), MORNING, False),  # an earlier one loses
        ("garbage", MORNING, True),  # unparseable (an owner's own edit, say): nothing to lose to
        # An owner typing a date by hand (issue #48: the page is meant to be
        # hand-edited) is a likelier source of a naive value than record()
        # ever writing one; comparing it to an aware `now` must not raise.
        ("2026-09-19T14:00:00", MORNING, True),
    ], ids=["no-prior", "later", "earlier", "unparseable", "naive"])
    def test_latest_edition(self, prior_at, now, expected):
        assert rec._is_latest_edition(prior_at, now) is expected


class TestRecord:
    def test_the_day_page_keeps_the_card_and_the_research_and_is_listed(self, mac, tmp_path):
        out = rec.record(Wiki(mac.call_tool), edition(tmp_path), "cht_1", MORNING)
        assert out == f"RECORDED {EDITIONS}/2026-09-19.md"
        meta, body = split_page(day(mac))
        assert meta["priority"]["recommendations"][0]["first_step"] == "Send Raj the pilot terms"
        assert {"resource": "https://news.example/fx"} in meta["sources"]
        assert {"resource": "https://example.com/blueprint"} in meta["sources"]
        assert "https://example.com/acme" not in day(mac)
        assert "Acme asked for pilot terms (Gmail)" in body
        assert "### 1. Close the Acme pilot" in body
        assert "Proof beats promises." in body
        assert "Q1 — Which customer would publicly vouch for you?" in body
        assert "BRL up 1% on Sep 18 (https://news.example/fx)" in body
        assert "Could not source: the central bank's comment" in body
        assert "editions/2026-09-19.md" in (mac.home / "Plow" / "wiki" / OVERVIEW).read_text()

    def test_a_topic_id_section_with_no_desk_is_still_recorded_as_news(self, mac, tmp_path):
        # render_edition.py's desk_of() already renders a no-desk topic_id
        # section as news; record_edition.py must agree (fill_news_desk is
        # shared), or the owner would receive it and the archive drop it.
        sections = [{"kind": "section", "topic_id": "t_no_desk", "title": "The dollar",
                     "headline": "The real firms", "body": "The real rose 1%.",
                     "sources": ["https://news.example/fx"]}]
        run_dir = tmp_path / "run" / "daily-2026-09-19"
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "edition.json"
        path.write_text(json.dumps({"date": "2026-09-19", "location": "Sao Paulo", "sections": sections}))
        rec.record(Wiki(mac.call_tool), path, "cht_1", MORNING)
        assert "The real rose 1%." in day(mac)

    def test_the_owners_own_accounts_stay_off_the_wiki(self, mac, tmp_path):
        rec.record(Wiki(mac.call_tool), edition(tmp_path), "cht_1", MORNING)
        assert "Rain in Sao Paulo" not in day(mac) and "Ana Costa" not in day(mac)
        assert "Dentist" not in day(mac)

    def test_a_later_edition_appends_and_its_card_is_the_days(self, mac, tmp_path):
        w = Wiki(mac.call_tool)
        rec.record(w, edition(tmp_path), "cht_1", MORNING)
        rec.record(w, edition(tmp_path, headline="Book the Acme demo"), "cht_1", AFTERNOON)
        meta, body = split_page(day(mac))
        assert "## 06:04 edition" in body and "## 14:00 edition" in body
        assert meta["priority"]["headline"] == "Book the Acme demo"

    def test_out_of_order_recording_still_keeps_the_chronologically_latest_card(self, mac, tmp_path):
        # issue #48: two papers can finish recording out of order, and by a
        # sub-second margin -- two editions the same minute, half a second
        # apart. The later one's write lands first here; the earlier one's
        # arrives second but must not overwrite it, and priority_at keeps
        # full precision so the two do not compare equal.
        earlier = AFTERNOON
        later = AFTERNOON.replace(microsecond=500_000)
        w = Wiki(mac.call_tool)
        rec.record(w, edition(tmp_path, headline="Later this second"), "cht_1", later)
        rec.record(w, edition(tmp_path, headline="Earlier this second"), "cht_1", earlier)
        meta, body = split_page(day(mac))
        assert body.count("## 14:00 edition") == 2
        assert meta["priority"]["headline"] == "Later this second"
        assert meta["priority_at"] == later.isoformat()

        # A third write landing last in wall-clock time, but for an edition
        # delivered well before both above, must not move "updated"
        # backward either -- the page would announce an older update than
        # the write that already landed (srosro-review, contract-drift).
        rec.record(w, edition(tmp_path, headline="Much earlier"), "cht_1", MORNING)
        meta = split_page(day(mac))[0]
        assert meta["updated"] == later.isoformat(timespec="seconds")

    def test_the_same_edition_twice_is_recorded_once(self, mac, tmp_path):
        w, path = Wiki(mac.call_tool), edition(tmp_path)
        rec.record(w, path, "cht_1", MORNING)
        before = day(mac)
        assert rec.record(w, path, "cht_1", MORNING).startswith("SKIPPED:")
        assert day(mac) == before

    def test_a_skipped_repeat_still_checks_the_wiki(self, mac, tmp_path, monkeypatch):
        # A retry must still finish an earlier check() that failed after the
        # write landed -- the marker means "don't append again", never
        # "don't index again".
        w, path = Wiki(mac.call_tool), edition(tmp_path)
        calls, real_check = [], Wiki.check

        def spy_check(self):
            calls.append(1)
            return real_check(self)

        monkeypatch.setattr(Wiki, "check", spy_check)
        rec.record(w, path, "cht_1", MORNING)
        before = day(mac)
        rec.record(w, path, "cht_1", MORNING)
        assert calls == [1, 1]
        assert day(mac) == before

    def test_an_edition_of_standing_desks_only_leaves_no_page(self, mac, tmp_path):
        out = rec.record(Wiki(mac.call_tool), edition(tmp_path, card=False, news=False), "cht_1", MORNING)
        assert out.startswith("SKIPPED:")
        assert not (mac.home / "Plow" / "wiki" / EDITIONS).exists()

    def test_a_news_block_is_addressable_by_its_topic_id(self, mac, tmp_path):
        # history.py reads a section's own past record back out of the day
        # page's frontmatter, not the Markdown body -- the heading text is
        # the owner's words and can be restated, so the topic id is what
        # makes a section findable.
        rec.record(Wiki(mac.call_tool), edition(tmp_path), "cht_1", MORNING)
        meta = split_page(day(mac))[0]
        assert meta["sections"]["t_9f2a"] == {
            "headline": "The real firms",
            "printed": [{"claim": "BRL up 1% on Sep 18", "url": "https://news.example/fx"}]}
        assert "t_1234" not in meta["sections"]  # mail is the owner's own account

    def test_a_later_editions_missing_headline_keeps_the_earlier_one(self, mac, tmp_path):
        # render_edition.py's `elif headline:` guard allows a section with no
        # headline; a later same-day edition like that must not blank a
        # headline an earlier edition already gave the section, and a
        # claim/url repeated between editions must not be recorded twice.
        w = Wiki(mac.call_tool)
        second_notes = [{"claim": "BRL up 1% on Sep 18", "url": "https://news.example/fx"},
                         {"claim": "BRL steady by close", "url": "https://news.example/fx2"}]
        rec.record(w, edition(tmp_path, card=False), "cht_1", MORNING)
        rec.record(w, edition(tmp_path, card=False, news_headline="", notes=second_notes), "cht_1", AFTERNOON)
        meta = split_page(day(mac))[0]
        assert meta["sections"]["t_9f2a"] == {
            "headline": "The real firms",
            "printed": [{"claim": "BRL up 1% on Sep 18", "url": "https://news.example/fx"},
                        {"claim": "BRL steady by close", "url": "https://news.example/fx2"}]}


class TestCli:
    def test_an_unreachable_mac_fails_loudly(self, mac, monkeypatch, tmp_path):
        path = edition(tmp_path)
        mac.asleep = True
        monkeypatch.setattr(rec, "connect", lambda: Wiki(mac.call_tool))
        monkeypatch.setenv("PLOW_HOME_CHANNEL", "cht_1")
        with pytest.raises(SystemExit) as exc:
            rec.main([str(path)])
        assert str(exc.value).startswith("error: edition not recorded — Mac unreachable")

    def test_the_heading_uses_the_owners_clock_not_the_containers(self, mac, monkeypatch, tmp_path):
        # 23:30 on the container's own day is already 13:30 the next day in
        # a +14 zone: the heading must show the owner's hour, never the
        # container's, so main() has to call owner_now(), not datetime.now().
        path = edition(tmp_path)
        far_east = timezone(timedelta(hours=14))
        owner_instant = datetime(2026, 9, 20, 13, 30, tzinfo=far_east)
        monkeypatch.setattr(rec, "connect", lambda: Wiki(mac.call_tool))
        monkeypatch.setattr(rec, "owner_now", lambda: owner_instant)
        monkeypatch.setenv("PLOW_HOME_CHANNEL", "cht_1")
        rec.main([str(path)])
        assert "## 13:30 edition" in day(mac)

    def test_now_flag_uses_the_delivery_moment_instead_of_owner_now(self, mac, monkeypatch, tmp_path):
        # issue #48: post_to_chat.py passes the timestamp it captured right
        # after the chat POST, so a slow print step run afterward cannot
        # stand in for this edition's own time.
        path = edition(tmp_path)
        monkeypatch.setattr(rec, "connect", lambda: Wiki(mac.call_tool))
        monkeypatch.setattr(rec, "owner_now", lambda: MORNING)  # must not be used
        monkeypatch.setenv("PLOW_HOME_CHANNEL", "cht_1")
        rec.main([str(path), "--now", AFTERNOON.isoformat()])
        assert "## 14:00 edition" in day(mac)

    def test_an_unparseable_now_flag_is_refused_by_name(self, mac, tmp_path):
        with pytest.raises(SystemExit, match="--now 'garbage' is not ISO8601"):
            rec.main([str(edition(tmp_path)), "--now", "garbage"])
