"""register_crons.py -- the spec derivation and the refusals with teeth."""
from __future__ import annotations

import json

import pytest

from conftest import ROOT, load_module

crons = load_module("pt_crons", "pt-dashboard/scripts/register_crons.py")

TZ = "America/Los_Angeles"
FUTURE = "2099-01-01T07:03:00-03:00"
CONFIG = {
    "owner": {"timezone": TZ},
    "delivery": {"hour": "07:00"},
    "printer": {"configured": False, "name": None},
}


def topic(tid, kind="subscription", status="pending", depth="deep", run_on=None,
          deliver_at=None):
    row = {"id": tid, "text": f"topic {tid}", "kind": kind, "depth": depth,
           "status": status, "created_at": "now", "last_edition_at": None,
           "scheduled_for": None, "run_on": run_on}
    if deliver_at is not None:
        row["deliver_at"] = deliver_at
    return row


def write_config(tmp_path, config=CONFIG):
    path = tmp_path / "pt" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config))
    return path


def write_jobs(tmp_path, jobs):
    path = tmp_path / "jobs.json"
    if jobs is None:
        return path  # absent: the only empty-schedule answer
    path.write_text(json.dumps({"jobs": jobs}))
    return path


def job(name, enabled=True, paused_at=None):
    return {"name": name, "enabled": enabled, "paused_at": paused_at}


class TestRegisteredJobs:
    def test_missing_file_is_the_only_empty_answer(self, tmp_path):
        assert crons.registered_jobs(tmp_path / "jobs.json") == {}

    def test_garbage_aborts(self, tmp_path):
        with pytest.raises(Exception):
            crons.registered_jobs(write_jobs(tmp_path, "garbage"))

    def test_wrong_shape_aborts(self, tmp_path):
        path = tmp_path / "jobs.json"
        path.write_text(json.dumps({"nope": []}))
        with pytest.raises(Exception):
            crons.registered_jobs(path)

    def test_paused_is_registered_but_not_runnable(self, tmp_path):
        registered = crons.registered_jobs(write_jobs(tmp_path, [
            job("pt-subscription-t_9f2a"),
            job("pt-subscription-t_0c11", enabled=False),
            job("pt-subscription-t_dead", paused_at="2026-09-09"),
        ]))
        assert registered == {
            "pt-subscription-t_9f2a": True,
            "pt-subscription-t_0c11": False,
            "pt-subscription-t_dead": False,
        }


class TestLoadZones:
    def test_empty_tz_refuses(self, tmp_path):
        path = write_config(tmp_path)
        with pytest.raises(SystemExit, match="TZ is empty"):
            crons.load_zones(path, env={})

    def test_names_both_clocks(self, tmp_path):
        path = write_config(tmp_path)
        assert crons.load_zones(path, env={"TZ": "America/Chicago"}) == (TZ, "America/Chicago")

    def test_blank_owner_timezone_refuses(self, tmp_path):
        blank_tz_config = {**CONFIG, "owner": {"timezone": ""}}
        path = write_config(tmp_path, config=blank_tz_config)
        with pytest.raises(SystemExit, match="blank owner.timezone"):
            crons.load_zones(path, env={"TZ": TZ})

    def test_missing_config_refuses(self, tmp_path):
        with pytest.raises(SystemExit, match="missing"):
            crons.load_zones(tmp_path / "nope.json", env={"TZ": TZ})


class TestResolveDeliver:
    def test_expands(self):
        env = {"PLOW_HOME_CHANNEL": "chat_123"}
        assert crons.resolve_deliver("plow_chat:${PLOW_HOME_CHANNEL}", env) == \
            "plow_chat:chat_123"

    def test_blank_refuses_by_name(self):
        with pytest.raises(SystemExit, match="PLOW_HOME_CHANNEL"):
            crons.resolve_deliver("plow_chat:${PLOW_HOME_CHANNEL}", {})


class TestDesiredJobs:
    def test_one_job_per_active_subscription(self, tmp_path):
        path = write_config(tmp_path)
        topics = [topic("t_9f2a"), topic("t_0c11")]
        jobs = crons.desired_jobs(topics, "07:00", TZ, TZ, {"PLOW_HOME_CHANNEL": "c"})
        assert [j["name"] for j in jobs] == [
            crons.DAILY_NAME,
            "pt-subscription-t_9f2a", "pt-subscription-t_0c11"]
        subs = [j for j in jobs if j["name"].startswith("pt-subscription-")]
        assert all(j["schedule"] == "0 7 * * *" for j in subs)
        assert all(j["deliver"] == crons.DELIVER_TARGET for j in jobs)
        assert path.name == "config.json"  # config untouched

    def test_early_extra_slot_clamps_its_lead_instead_of_refusing(self):
        # The main paper's 40-minute lead must not abort registration for a
        # slot at 00:20: that slot starts at midnight, not the evening before.
        jobs = crons.desired_jobs(
            [topic("t_9f2a", kind="section", deliver_at="12:30")], "07:00", TZ, TZ,
            {"PLOW_HOME_CHANNEL": "c"}, lead_minutes=40, extra_hours=["00:20"])
        by_name = {j["name"]: j["schedule"] for j in jobs}
        assert by_name[crons.DAILY_NAME] == "20 6 * * *"
        assert by_name[f"{crons.DAILY_NAME}-2"] == "0 0 * * *"
        assert by_name[crons.paper_job_name("12:30")] == "50 11 * * *"

    def test_slot_clamps_to_owner_midnight_when_zones_differ(self):
        # Owner UTC-3, container UTC: the owner's 00:20 is 03:20 on the
        # container. The 40-minute lead stops at owner midnight (03:00
        # container); the owner's 10:30 (13:30) keeps the full lead.
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section", deliver_at="14:30")], "00:20",
            "America/Sao_Paulo", "UTC", {}, 40, extra_hours=["10:30"],
        )
        assert jobs[0]["schedule"] == "0 3 * * *"
        assert jobs[1]["schedule"] == "50 12 * * *"
        assert jobs[2]["schedule"] == "50 16 * * *"

    def test_every_job_fires_on_the_container_clock(self):
        # The owner's 07:00 in Tokyo (+09) is 22:00 the evening before in UTC.
        jobs = crons.desired_jobs(
            [topic("t_9f2a"), topic("t_1", kind="section", deliver_at="12:00")], "07:00",
            "Asia/Tokyo", "UTC")
        by_name = {j["name"]: j for j in jobs}
        daily = by_name[crons.DAILY_NAME]
        assert daily["schedule"] == "0 22 * * *"
        assert "--hold-until 22:00 " in daily["prompt"]
        assert by_name["pt-subscription-t_9f2a"]["schedule"] == "0 22 * * *"
        # The focused paper keeps the owner's hour as its name and roster key.
        paper = by_name[crons.paper_job_name("12:00")]
        assert "--deliver-at 12:00" in paper["prompt"]
        assert paper["schedule"] == "0 3 * * *"

    @pytest.mark.parametrize("owner_tz", ["America/Los_Angeles", "Asia/Tokyo"])
    def test_local_hour_from_before_owner_clock_hours_is_retired_never_copied(
            self, tmp_path, owner_tz):
        # setup may already have written a new owner-clock hour beside the
        # stale local_hour; adoption only ever drops the key.
        legacy = {**CONFIG, "owner": {"timezone": owner_tz},
                  "delivery": {"hour": "05:00", "local_hour": "04:00", "extra_hours": ["10:00"]}}
        path = write_config(tmp_path, legacy)
        if owner_tz != "America/Los_Angeles":
            with pytest.raises(SystemExit, match="predates owner-clock hours"):
                crons.adopt_owner_clock(owner_tz, "America/Los_Angeles", path)
            assert json.loads(path.read_text()) == legacy
            return
        for _ in range(2):  # the second run finds nothing to redo
            crons.adopt_owner_clock(owner_tz, "America/Los_Angeles", path)
        assert json.loads(path.read_text())["delivery"] == {"hour": "05:00", "extra_hours": ["10:00"]}

    @pytest.mark.parametrize("delivery, hours", [
        ({"hour": "07:00"}, []),
        ({"hour": "07:00", "extra_hours": None}, []),
        ({"hour": "07:00", "extra_hours": ["10:30"]}, ["10:30"]),
    ])
    def test_extra_hours_absent_or_null_is_none(self, tmp_path, delivery, hours):
        path = write_config(tmp_path, {**CONFIG, "delivery": delivery})
        assert crons.load_extra_hours(path) == hours

    def test_cancelled_subscription_gets_no_job(self):
        jobs = crons.desired_jobs(
            [topic("t_9f2a", status="cancelled")], "07:00", TZ, TZ, {})
        assert [j["name"] for j in jobs] == [crons.DAILY_NAME]

    @pytest.mark.parametrize("status,scheduled_for,fires_at", [
        ("pending", FUTURE, [FUTURE]),
        ("pending", "2000-01-01T07:03:00-03:00", []),  # past: not re-armed
        ("running", FUTURE, []),
        ("delivered", FUTURE, []),
    ])
    def test_only_a_pending_one_off_still_ahead_gets_its_job(
            self, status, scheduled_for, fires_at):
        oneoff = {**topic("t_0c11", kind="one_off", status=status, depth="quick"),
                  "scheduled_for": scheduled_for}
        jobs = crons.desired_jobs([oneoff], "07:00", TZ, TZ, {})
        assert [j["schedule"] for j in jobs if j["name"] == "pt-oneoff-t_0c11"] == fires_at

    def test_running_subscription_still_has_its_job(self):
        jobs = crons.desired_jobs([topic("t_9f2a", status="running")], "07:00", TZ, TZ, {})
        assert [j["name"] for j in jobs] == [crons.DAILY_NAME, "pt-subscription-t_9f2a"]

    def test_hour_derived_without_leading_zero(self):
        jobs = crons.desired_jobs([topic("t_9f2a")], "23:00", TZ, TZ, {})
        sub = next(j for j in jobs if j["name"] == "pt-subscription-t_9f2a")
        assert sub["schedule"] == "0 23 * * *"


class TestStaleNames:
    def test_cancelled_subscription_pruned(self):
        stale = crons.stale_names(
            [topic("t_9f2a", status="cancelled")],
            {"pt-subscription-t_9f2a": True},
        )
        assert stale == ["pt-subscription-t_9f2a"]

    def test_delivered_oneoff_pruned(self):
        stale = crons.stale_names(
            [topic("t_0c11", kind="one_off", status="delivered", depth="quick")],
            {"pt-oneoff-t_0c11": True},
        )
        assert stale == ["pt-oneoff-t_0c11"]

    def test_pending_oneoff_kept(self):
        stale = crons.stale_names(
            [topic("t_0c11", kind="one_off", status="pending", depth="quick")],
            {"pt-oneoff-t_0c11": True},
        )
        assert stale == []

    def test_job_with_no_topic_pruned(self):
        assert crons.stale_names([], {"pt-subscription-t_ffff": True}) == \
            ["pt-subscription-t_ffff"]

    def test_foreign_names_never_touched(self):
        registered = {"ld-weather": True, "pt-subscription-notanid": True,
                      "pt-subscription-t_9f2a-extra": True}
        assert crons.stale_names([topic("t_9f2a")], registered) == []


class TestCreateArgv:
    def test_argv_shape(self):
        jobs = crons.desired_jobs([topic("t_9f2a")], "07:00", TZ, TZ,
                                  {"PLOW_HOME_CHANNEL": "chat_123"})
        sub = next(j for j in jobs if j["name"] == "pt-subscription-t_9f2a")
        argv = crons.create_argv(sub, {"PLOW_HOME_CHANNEL": "chat_123"})
        assert argv[0:5] == [crons.HERMES, "cron", "create", "0 7 * * *",
                             argv[4]]
        assert "--name" in argv and "pt-subscription-t_9f2a" in argv
        assert "--deliver" in argv and "plow_chat:chat_123" in argv
        assert argv[argv.index("--deliver") + 1] == "plow_chat:chat_123"


class TestEditArgv:
    def test_argv_updates_in_place(self):
        jobs = crons.desired_jobs([topic("t_9f2a")], "07:00", TZ, TZ,
                                  {"PLOW_HOME_CHANNEL": "chat_123"})
        daily = next(j for j in jobs if j["name"] == crons.DAILY_NAME)
        argv = crons.edit_argv(daily, {"PLOW_HOME_CHANNEL": "chat_123"})
        assert argv[:4] == [crons.HERMES, "cron", "edit", crons.DAILY_NAME]
        assert argv[argv.index("--schedule") + 1] == daily["schedule"]
        assert argv[argv.index("--prompt") + 1] == daily["prompt"]
        assert argv[argv.index("--skill") + 1] == daily["skill"]
        assert argv[argv.index("--deliver") + 1] == "plow_chat:chat_123"
        assert argv[2] == "edit"



class TestMain:
    @pytest.fixture
    def hermes(self, tmp_path, monkeypatch):
        fake = tmp_path / "hermes"
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)
        monkeypatch.setattr(crons, "HERMES", str(fake))
        return fake

    def run_main(self, tmp_path, monkeypatch, topics_list, registered,
                 calls=None, runner=None, env=None, argv=None):
        pt_home = tmp_path / "pt"
        pt_home.mkdir(exist_ok=True)
        (pt_home / "config.json").write_text(json.dumps(CONFIG))
        (pt_home / "topics.json").write_text(json.dumps({"topics": topics_list}))
        jobs_path = write_jobs(tmp_path, registered)
        monkeypatch.setenv("PT_HOME", str(pt_home))
        monkeypatch.chdir(tmp_path)

        if runner is None:
            def runner(argv):
                if calls is not None:
                    calls.append(argv)
                return type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()

        return crons.main(
            argv,
            jobs_path=jobs_path,
            config_path=pt_home / "config.json",
            env=env if env is not None else {"TZ": TZ, "PLOW_HOME_CHANNEL": "chat_123"},
            runner=runner,
        )

    def test_now_queues_the_main_papers_own_prompt_as_a_one_shot(
            self, tmp_path, monkeypatch, hermes, capsys):
        # "Send me the paper now" is the SAME job the 7am cron runs. Measured
        # live: a live variant of the recipe skipped the advisor, so an
        # on-demand paper came back with a gap card and one story.
        calls = []
        rc = self.run_main(tmp_path, monkeypatch, [], [job(crons.DAILY_NAME)],
                           calls=calls, argv=["--now"])
        assert rc == 0
        (create,) = [c for c in calls if crons.NOW_NAME in c]
        schedule, prompt = create[3], create[4]
        assert "T" in schedule  # an ISO instant: hermes fires it once
        assert prompt == crons.paper_prompt()
        assert create[create.index("--deliver") + 1] == "plow_chat:chat_123"
        assert "queued: pt-daily-edition-now" in capsys.readouterr().out

    @pytest.mark.parametrize("create_rc", [0, 1])
    def test_now_removes_the_previous_one_shot_only_after_queueing_its_successor(
            self, tmp_path, monkeypatch, hermes, create_rc):
        # A failed create must not cancel a copy the owner was already promised.
        calls = []

        def runner(argv):
            calls.append(argv)
            rc = create_rc if argv[2] == "create" and crons.NOW_NAME in argv else 0
            return type("P", (), {"returncode": rc, "stdout": "", "stderr": ""})()

        previous = {**job(crons.NOW_NAME), "id": "old123"}

        def run():
            return self.run_main(tmp_path, monkeypatch, [], [job(crons.DAILY_NAME), previous],
                                 runner=runner, argv=["--now"])
        if create_rc:
            with pytest.raises(SystemExit, match="could not queue"):
                run()
            assert not any(c[2] == "remove" for c in calls)
        else:
            run()
            now = [c[2:4] for c in calls if crons.NOW_NAME in c or "old123" in c]
            assert [c[0] for c in now] == ["create", "remove"] and now[1][1] == "old123"

    def test_rebuild_recreates_a_pending_one_offs_job(self, tmp_path, monkeypatch, hermes):
        # A rebuilt home replays jobs.json from topics.json: a one-off the
        # owner was promised must come back like any subscription does.
        calls = []
        oneoff = {**topic("t_0c11", kind="one_off", depth="quick"), "scheduled_for": FUTURE}
        self.run_main(tmp_path, monkeypatch, [oneoff], [job(crons.DAILY_NAME)], calls=calls)
        (create,) = [c for c in calls if "pt-oneoff-t_0c11" in c]
        assert create[2:4] == ["create", FUTURE]
        assert "topic t_0c11 now (depth quick)" in create[4]
        assert create[create.index("--deliver") + 1] == "plow_chat:chat_123"

    def test_registration_never_sweeps_a_queued_copy(self):
        assert crons.stale_names([], {crons.NOW_NAME: True}, delivery_hour="07:00") == []

    def test_registers_missing_subscription(
            self, tmp_path, monkeypatch, hermes):
        calls = []
        code = self.run_main(tmp_path, monkeypatch,
                             [topic("t_9f2a")], [], calls=calls)
        assert code == 0
        assert any("create" in " ".join(c) for c in calls)

    def test_idempotent_run_skips_present(self, tmp_path, monkeypatch, hermes):
        calls = []
        code = self.run_main(tmp_path, monkeypatch, [topic("t_9f2a")],
                             [job(crons.DAILY_NAME), job("pt-subscription-t_9f2a")],
                             calls=calls)
        assert code == 0
        assert calls == []  # nothing created, nothing removed

    def test_removes_stale_and_creates_missing(
            self, tmp_path, monkeypatch, hermes):
        calls = []
        code = self.run_main(
            tmp_path, monkeypatch,
            [topic("t_0c11")],  # t_0c11 active; t_ffff job orphaned
            [job("pt-subscription-t_ffff")], calls=calls)
        assert code == 0
        assert any("remove" in c and "pt-subscription-t_ffff" in c for c in calls)
        assert any("create" in " ".join(c) and "pt-subscription-t_0c11" in " ".join(c)
                   for c in calls)

    def test_failed_create_lears_loud(self, tmp_path, monkeypatch, hermes):
        def failing(argv):
            return type("P", (), {"returncode": 1, "stdout": "boom",
                                  "stderr": "bad schedule"})()
        with pytest.raises(SystemExit, match="could not register"):
            self.run_main(tmp_path, monkeypatch, [topic("t_9f2a")], [],
                          runner=failing)

    def test_blank_home_channel_refuses(self, tmp_path, monkeypatch, hermes):
        with pytest.raises(SystemExit, match="PLOW_HOME_CHANNEL"):
            self.run_main(tmp_path, monkeypatch, [topic("t_9f2a")], [],
                          env={"TZ": TZ})


class TestDailySchedule:
    def test_default_lead_is_zero(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section")], "07:00", TZ, TZ, {})
        assert jobs[0]["schedule"] == "0 7 * * *"
        assert crons.DEFAULT_LEAD_MINUTES == 0

    @pytest.mark.parametrize("hour, lead, schedule", [
        ("07:00", 45, "15 6 * * *"),
        ("07:00", 0, "0 7 * * *"),
        # The owner's minute is kept, with or without a lead.
        ("10:25", 0, "25 10 * * *"),
        ("10:25", 10, "15 10 * * *"),
        ("00:30", 30, "0 0 * * *"),
    ])
    def test_lead_is_subtracted_in_minutes(self, hour, lead, schedule):
        assert crons.daily_schedule(hour, lead) == schedule

    def test_lead_past_midnight_refuses(self):
        # That run would fire the evening before: the previous day's paper.
        with pytest.raises(SystemExit, match="before midnight of its delivery day"):
            crons.daily_schedule("00:30", 31)

    def test_lead_past_179_minutes_loads(self, tmp_path):
        path = write_config(tmp_path, {**CONFIG, "delivery": {"hour": "23:00", "lead_minutes": 200}})
        assert crons.load_lead_minutes(path) == 200

    def test_negative_lead_refuses(self, tmp_path):
        path = write_config(tmp_path, {**CONFIG, "delivery": {"hour": "07:00", "lead_minutes": -1}})
        with pytest.raises(SystemExit, match="non-negative integer"):
            crons.load_lead_minutes(path)


class TestSubscriptionJob:
    def test_carries_the_owner_chosen_minute(self):
        job = crons.subscription_job(topic("t_9f2a"), "10:25")
        assert job["schedule"] == "25 10 * * *"

    def test_whole_hour_still_works(self):
        job = crons.subscription_job(topic("t_9f2a"), "07:00")
        assert job["schedule"] == "0 7 * * *"


class TestExtraDailyHours:
    # Regression: a user asked for a second daily edition at 10:30 and the
    # model, having no sanctioned way to do that, hand-registered a cron job
    # by shell command instead -- wrong schedule (17 minutes from creation
    # time, not 10:30), a name (pt-daily-edition-2) this script didn't know
    # to manage, and a hand-typed prompt that dropped the --pdf leg. These
    # tests are the real feature that makes the hand-rolled version
    # unnecessary.
    def test_desired_jobs_adds_one_per_extra_hour(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section")], "03:00", TZ, TZ, {"PLOW_HOME_CHANNEL": "c"},
            45, extra_hours=["10:30"],
        )
        names = [j["name"] for j in jobs]
        assert names == ["pt-daily-edition", "pt-daily-edition-2"]
        # Each slot gets its own lead-time subtraction -- 10:30 minus 45m.
        assert jobs[1]["schedule"] == "45 9 * * *"
        assert jobs[1]["skill"] == "pt-research"
        assert jobs[1]["deliver"] == crons.DELIVER_TARGET

    def test_extra_job_prompt_shares_the_workspace_lock_and_has_the_pdf_leg(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section")], "03:00", TZ, TZ, {}, 45, extra_hours=["10:30"],
        )
        prompt = jobs[1]["prompt"]
        assert "paper-workspace-<today's date" in prompt
        assert "post_to_chat.py" in prompt
        assert "NO_REPLY" in prompt

    def test_no_extra_hours_is_unchanged(self):
        jobs = crons.desired_jobs([topic("t_1", kind="section")], "03:00", TZ, TZ, {}, 45)
        assert [j["name"] for j in jobs] == ["pt-daily-edition"]

    @pytest.mark.parametrize("extra,section_hour", [
        (["09:00"], None),
        ([], "09:00"),
    ])
    def test_papers_less_than_three_hours_apart_are_refused(self, extra, section_hour):
        topics = [topic("t_1", kind="section", deliver_at=section_hour)] if section_hour else []

        with pytest.raises(SystemExit, match="paper times 07:00 and 09:00 are less than 180 minutes apart"):
            crons.desired_jobs(topics, "07:00", TZ, TZ, {}, 0, extra_hours=extra)

    def test_multiple_extra_hours_are_numbered_in_order(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section")], "03:00", TZ, TZ, {}, 45,
            extra_hours=["10:30", "16:00"],
        )
        assert [j["name"] for j in jobs] == [
            "pt-daily-edition", "pt-daily-edition-2", "pt-daily-edition-3",
        ]

    def test_stale_extra_job_beyond_configured_count_is_pruned(self):
        stale = crons.stale_names(
            [topic("t_1", kind="section")],
            ["pt-daily-edition", "pt-daily-edition-2", "pt-daily-edition-3"],
            extra_hours_count=1,
        )
        assert stale == ["pt-daily-edition-3"]

    def test_extra_job_kept_when_still_configured(self):
        stale = crons.stale_names(
            [topic("t_1", kind="section")],
            ["pt-daily-edition", "pt-daily-edition-2"],
            extra_hours_count=1,
        )
        assert stale == []

    def test_extra_jobs_kept_when_news_topics_are_gone(self):
        stale = crons.stale_names(
            [], ["pt-daily-edition", "pt-daily-edition-2"], extra_hours_count=1,
        )
        assert stale == []


class TestFocusedPapers:
    def test_name_from_hour(self):
        assert crons.paper_job_name("12:30") == "pt-paper-1230"
        assert crons.paper_hour_from_name("pt-paper-1230") == "12:30"

    def test_desired_jobs_adds_one_job_per_distinct_hour(self):
        jobs = crons.desired_jobs(
            [
                topic("t_1", kind="section"),
                topic("t_2", kind="section", deliver_at="12:30"),
                topic("t_3", kind="section", deliver_at="12:30"),
                topic("t_4", kind="section", deliver_at="18:00"),
            ],
            "07:00", TZ, TZ, {}, 0,
        )
        names = [j["name"] for j in jobs]
        assert names == [
            "pt-daily-edition", "pt-paper-1230", "pt-paper-1800",
        ]
        assert jobs[1]["schedule"] == "30 12 * * *"
        assert jobs[2]["schedule"] == "0 18 * * *"
        assert "deliver_at is 12:30" in jobs[1]["prompt"]
        assert "paper-workspace-<today's date" in jobs[1]["prompt"]
        assert "NO_REPLY" in jobs[1]["prompt"]

    def test_deliver_at_equal_to_main_hour_rides_the_daily_job(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section", deliver_at="07:00")],
            "07:00", TZ, TZ, {}, 0,
        )
        assert [j["name"] for j in jobs] == ["pt-daily-edition"]

    def test_cancelled_timed_section_is_not_a_paper(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section", deliver_at="12:30", status="cancelled")],
            "07:00", TZ, TZ, {}, 0,
        )
        assert [j["name"] for j in jobs] == ["pt-daily-edition"]

    def test_papers_sit_between_extra_hours_and_subscriptions(self):
        jobs = crons.desired_jobs(
            [
                topic("t_1", kind="section", deliver_at="13:30"),
                topic("t_9f2a"),
            ],
            "07:00", TZ, TZ, {}, 0, extra_hours=["10:30"],
        )
        assert [j["name"] for j in jobs] == [
            "pt-daily-edition", "pt-daily-edition-2", "pt-paper-1330",
            "pt-subscription-t_9f2a",
        ]

    def test_stale_paper_is_pruned_when_hour_is_empty(self):
        stale = crons.stale_names(
            [topic("t_1", kind="section")],
            ["pt-daily-edition", "pt-paper-1230"],
            delivery_hour="07:00",
        )
        assert stale == ["pt-paper-1230"]

    def test_live_paper_is_kept(self):
        stale = crons.stale_names(
            [topic("t_1", kind="section", deliver_at="12:30")],
            ["pt-daily-edition", "pt-paper-1230"],
            delivery_hour="07:00",
        )
        assert stale == []

    def test_paper_without_delivery_hour_is_left_alone(self):
        stale = crons.stale_names(
            [],
            ["pt-paper-1230"],
        )
        assert stale == []


class TestDailyJob:
    def test_included_when_a_section_exists(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section", status="pending")], "07:00", TZ, TZ, {}, 45)
        assert jobs[0]["name"] == crons.DAILY_NAME
        assert jobs[0]["schedule"] == "15 6 * * *"
        assert jobs[0]["deliver"] == crons.DELIVER_TARGET
        assert jobs[0]["skill"] == "pt-research"

    def test_included_when_an_assignment_is_due(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="assignment", status="pending", run_on="2026-09-11")],
            "07:00", TZ, TZ, {}, 45)
        assert [j["name"] for j in jobs] == [crons.DAILY_NAME]

    def test_present_even_without_news_sections(self):
        jobs = crons.desired_jobs([topic("t_9f2a")], "07:00", TZ, TZ, {}, 45)
        assert [j["name"] for j in jobs] == [crons.DAILY_NAME, "pt-subscription-t_9f2a"]

    def test_daily_precedes_subscriptions(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section"), topic("t_9f2a")], "07:00", TZ, TZ, {}, 45)
        assert [j["name"] for j in jobs] == [
            crons.DAILY_NAME, "pt-subscription-t_9f2a"]


class TestDailyStale:
    def test_daily_kept_with_no_news_topics(self):
        assert crons.stale_names([], {crons.DAILY_NAME: True}) == []

    def test_daily_kept_while_a_section_lives(self):
        stale = crons.stale_names(
            [topic("t_1", kind="section")], {crons.DAILY_NAME: True})
        assert stale == []

    def test_daily_kept_while_an_assignment_runs(self):
        stale = crons.stale_names(
            [topic("t_1", kind="assignment", status="running", run_on="2026-09-11")],
            {crons.DAILY_NAME: True})
        assert stale == []


class TestDrift:
    def test_schedule_drift_detected(self):
        job = {"name": "pt-daily-edition", "schedule": "15 6 * * *", "skill": "pt-research"}
        spec = {"schedule": "0 7 * * *", "skill": "pt-research", "deliver": None}
        assert crons.job_drift(job, spec) is True

    def test_absent_schedule_is_not_drift(self):
        job = {"name": "pt-subscription-t_9f2a", "schedule": "0 7 * * *",
               "skill": "pt-research"}
        assert crons.job_drift(job, {}) is False

    def test_matching_spec_is_not_drift(self):
        job = {"name": "pt-daily-edition", "schedule": "15 6 * * *",
               "skill": "pt-research", "prompt": "same"}
        spec = {"schedule": "15 6 * * *", "skill": "pt-research",
                "prompt": "same", "deliver": "x"}
        assert crons.job_drift(job, spec) is False

    def test_prompt_drift_detected(self):
        job = {"name": "pt-daily-edition", "schedule": "15 6 * * *",
               "skill": "pt-research", "prompt": "post the PDF only"}
        spec = {"schedule": "15 6 * * *", "skill": "pt-research",
                "prompt": "return the edition as the final response"}
        assert crons.job_drift(job, spec) is True

    def test_absent_prompt_is_not_drift(self):
        job = {"name": "pt-daily-edition", "schedule": "15 6 * * *",
               "skill": "pt-research", "prompt": "new prompt"}
        spec = {"schedule": "15 6 * * *", "skill": "pt-research"}
        assert crons.job_drift(job, spec) is False

    def test_skill_drift_detected(self):
        job = {"name": "pt-daily-edition", "schedule": "15 6 * * *", "skill": "pt-edition"}
        spec = {"schedule": "15 6 * * *", "skill": "pt-research", "deliver": None}
        assert crons.job_drift(job, spec) is True

    def test_registered_specs_reads_fields(self, tmp_path):
        path = tmp_path / "jobs.json"
        path.write_text(json.dumps({"jobs": [
            {"name": "pt-daily-edition", "schedule": "15 6 * * *",
             "skill": "pt-research", "deliver": "plow_chat:c", "enabled": True,
             "paused_at": None},
        ]}))
        specs = crons.registered_specs(path)
        assert specs["pt-daily-edition"]["schedule"] == "15 6 * * *"

    def test_registered_specs_unwraps_the_real_schedule_shape(self, tmp_path):
        # A real registered job's "schedule" is a dict, not a bare string --
        # {"kind": "cron", "expr": "...", "display": "..."}. Measured against
        # this fleet's own jobs.json, not a guess: comparing that dict
        # straight to a spec's plain string made job_drift() true for every
        # managed job on every run.
        path = tmp_path / "jobs.json"
        path.write_text(json.dumps({"jobs": [
            {"name": "pt-daily-edition",
             "schedule": {"kind": "cron", "expr": "15 2 * * *", "display": "15 2 * * *"},
             "skill": "pt-research", "deliver": "plow_chat:c"},
        ]}))
        specs = crons.registered_specs(path)
        assert specs["pt-daily-edition"]["schedule"] == "15 2 * * *"

    def test_no_drift_against_the_real_schedule_shape(self):
        # The regression this whole helper exists for: an UNCHANGED job,
        # read back in its real persisted shape, must not read as drifted.
        job = {"name": "pt-daily-edition", "schedule": "15 2 * * *", "skill": "pt-research"}
        real_spec = {
            "schedule": crons._persisted_schedule_expr(
                {"schedule": {"kind": "cron", "expr": "15 2 * * *", "display": "15 2 * * *"}}
            ),
            "skill": "pt-research",
            "deliver": "plow_chat:c",
        }
        assert not crons.job_drift(job, real_spec)


class TestDriftMain:
    @pytest.fixture
    def hermes(self, tmp_path, monkeypatch):
        fake = tmp_path / "hermes"
        fake.write_text("#!/bin/sh\nexit 0\n")
        fake.chmod(0o755)
        monkeypatch.setattr(crons, "HERMES", str(fake))
        return fake

    def run_main(self, tmp_path, monkeypatch, topics_list, registered, runner,
                 env=None):
        pt_home = tmp_path / "pt"
        pt_home.mkdir(exist_ok=True)
        (pt_home / "config.json").write_text(json.dumps(CONFIG))
        (pt_home / "topics.json").write_text(json.dumps({"topics": topics_list}))
        jobs_path = write_jobs(tmp_path, registered)
        monkeypatch.setenv("PT_HOME", str(pt_home))
        monkeypatch.chdir(tmp_path)
        return crons.main(
            jobs_path=jobs_path,
            config_path=pt_home / "config.json",
            env=env if env is not None else {"TZ": TZ, "PLOW_HOME_CHANNEL": "chat_123"},
            runner=runner,
        )

    def test_drifted_job_edited_in_place(self, tmp_path, monkeypatch, hermes):
        calls = []
        def runner(argv):
            calls.append(argv)
            return type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
        code = self.run_main(
            tmp_path, monkeypatch,
            [topic("t_1", kind="section")],
            [{"name": crons.DAILY_NAME, "enabled": True, "paused_at": None,
              "schedule": "15 6 * * *", "skill": "pt-research"}],
            runner)
        assert code == 0
        assert any("edit" in c for c in calls)
        assert not any("remove" in c for c in calls)
        assert not any("create" in " ".join(c) for c in calls)
        edit = next(c for c in calls if "edit" in c)
        assert crons.DAILY_NAME in edit
        assert "--schedule" in edit

    def test_failed_edit_lears_loud(self, tmp_path, monkeypatch, hermes):
        def failing(argv):
            return type("P", (), {"returncode": 1, "stdout": "boom",
                                  "stderr": "no such job"})()
        with pytest.raises(SystemExit, match="could not update drifted job"):
            self.run_main(
                tmp_path, monkeypatch,
                [topic("t_1", kind="section")],
                [{"name": crons.DAILY_NAME, "enabled": True, "paused_at": None,
                  "schedule": "15 6 * * *", "skill": "pt-research"}],
                runner=failing,
            )

    def test_blank_channel_does_not_remove_a_drifted_job(
            self, tmp_path, monkeypatch, hermes):
        # Measured live 2026-09-18: docker compose exec had no
        # PLOW_HOME_CHANNEL (it lives in s6's root-only env). Drift
        # remove ran first; create_argv then refused; hermes cron list
        # was empty and the morning paper was gone.
        calls = []
        def runner(argv):
            calls.append(argv)
            return type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
        with pytest.raises(SystemExit, match="PLOW_HOME_CHANNEL"):
            self.run_main(
                tmp_path, monkeypatch,
                [topic("t_1", kind="section")],
                [{"name": crons.DAILY_NAME, "enabled": True, "paused_at": None,
                  "schedule": "15 6 * * *", "skill": "pt-research"}],
                runner=runner,
                env={"TZ": TZ},
            )
        assert calls == []

    def test_daily_kept_while_only_a_subscription_lives(self, tmp_path, monkeypatch, hermes):
        calls = []
        def runner(argv):
            calls.append(argv)
            return type("P", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
        self.run_main(
            tmp_path, monkeypatch,
            [topic("t_9f2a")],
            [{"name": crons.DAILY_NAME, "enabled": True, "paused_at": None}],
            runner)
        assert not any("remove" in c and crons.DAILY_NAME in c for c in calls)


def test_recipe_names_run_lock_as_a_bare_absolute_path():
    # "pt-shared's run_lock.py" with no path sent the model looking for an
    # invocation, then wrapping a shell.
    printed = crons.paper_prompt()
    assert (
        "/opt/plow/skills/pt-shared/scripts/run_lock.py acquire"
    ) in printed
    assert (
        "/opt/plow/skills/pt-shared/scripts/run_lock.py release"
    ) in printed
    assert (
        "/opt/plow/skills/pt-shared/scripts/prepare_daily_run.py"
    ) in printed
    assert "python3" not in printed


class TestCliPassesItsArguments:
    def test_module_entry_point_forwards_sys_argv(self):
        # main(argv=None) deliberately parses [] so an in-process caller never
        # reads pytest's own argv. That means the CLI entry MUST hand over
        # sys.argv[1:] explicitly, or no flag can ever be passed from a
        # terminal. Caught in the container: a flag was silently ignored and
        # the run fell through to plain registration.
        source = (ROOT / "pt-dashboard" / "scripts" / "register_crons.py").read_text()
        assert "main(sys.argv[1:])" in source, "the CLI entry drops its arguments"


class TestScheduledHold:
    """Two clocks: cron starts at hour−lead; POST waits for the hour."""

    def test_daily_job_holds_until_delivery_hour(self):
        jobs = crons.desired_jobs([], "07:00", TZ, TZ, {})
        prompt = jobs[0]["prompt"]
        assert "--hold-until 07:00" in prompt
        assert "--stale-minutes 240" in prompt

    def test_on_demand_copy_does_not_hold(self):
        p = crons.paper_prompt(lead_minutes=40)
        assert "--hold-until" not in p
        assert "--stale-minutes 280" in p

    def test_every_acquirer_of_the_daily_lock_outlives_the_early_start(self):
        # A scheduled run with a 40-minute lead holds the lock 40 minutes
        # before its own work; an on-demand copy must not call that stale.
        jobs = crons.desired_jobs([topic("t_1", kind="section")], "07:00", TZ, TZ, {}, 40)
        assert "--stale-minutes 280" in jobs[0]["prompt"]

    def test_paper_job_holds_until_its_hour(self):
        jobs = crons.desired_jobs(
            [topic("t_sec", kind="section", deliver_at="12:00")],
            "07:00", TZ, TZ, {},
        )
        paper = next(j for j in jobs if j["name"] == "pt-paper-1200")
        assert "--hold-until 12:00" in paper["prompt"]
        assert "--stale-minutes 240" in paper["prompt"]

    def test_extra_slot_holds_until_its_hour(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section")], "03:00", TZ, TZ, {}, 45, extra_hours=["10:30"],
        )
        assert "--hold-until 03:00" in jobs[0]["prompt"]
        assert "--hold-until 10:30" in jobs[1]["prompt"]


class TestRunPromptsDelegateDelivery:
    """post_to_chat.py prints, records and finalizes after its POST, so the
    model has no print step to skip. The prompts point at pt-edition step 2
    for delivery and never tell the model to print (that would double-print).
    """

    @pytest.mark.parametrize("p", [
        crons.paper_prompt(),
        crons.paper_prompt(focus="12:00"),
        crons.TOPIC_PROMPT,
    ])
    def test_prompt_delegates_delivery_to_the_edition_skill(self, p):
        assert "pt-edition/SKILL.md step 2" in p
        assert "post_to_chat.py" in p
        assert "pt-print" not in p and "print_edition" not in p
        assert "NO_REPLY" in p

    def test_paper_prompt_reopens_sections(self):
        assert "reopen-sections" in crons.paper_prompt()

    def test_all_papers_share_a_lock_longer_than_the_tournament(self):
        for prompt in (crons.paper_prompt("07:00"), crons.paper_prompt(focus="12:00")):
            assert "paper-workspace-<today's date" in prompt
            assert "--stale-minutes 240" in prompt

    def test_scheduled_papers_reuse_only_todays_advice(self):
        for prompt in (crons.paper_prompt("07:00"), crons.paper_prompt("12:00", focus="12:00")):
            assert "prepare_daily_run.py --preserve-priority" in prompt
            assert "reuse today's accepted checkpoint" in prompt
            assert "else run the tournament" in prompt

    def test_on_demand_copy_never_waits_on_a_tournament_it_can_reuse(self):
        # Owner's call: the copy reuses the newest accepted advice of any
        # date, printed with its as-of date; only a paper that has never had
        # accepted advice runs the tournament.
        prompt = crons.paper_prompt()
        assert "prepare_daily_run.py --preserve-priority" in prompt
        assert "newest accepted checkpoint" in prompt and "whatever its date" in prompt
        assert '"as_of"' in prompt
        assert "only if none has ever been accepted" in prompt
        assert "reuse today's" not in prompt

    @pytest.mark.parametrize("prompt", [
        crons.paper_prompt(),
        crons.paper_prompt(focus="12:00"),
    ])
    def test_paper_prompt_stops_before_research_on_legacy_overfill(self, prompt):
        assert "topics.py check-paper" in prompt
        assert "before research" in prompt
        refusal = prompt.index("If it refuses")
        release = prompt.index("run_lock.py release", refusal)
        research = prompt.index("Then run pt-research")
        assert refusal < release < research
