"""register_crons.py -- the spec derivation and the refusals with teeth."""
from __future__ import annotations

import json

import pytest

from conftest import ROOT, load_module

crons = load_module("pt_crons", "pt-dashboard/scripts/register_crons.py")
backend_mod = load_module("cron_backend", "pt-dashboard/scripts/cron_backend.py")

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


def row(name, enabled=True, jid=None, expr=None, tz=None, at=None, message=None, model=None):
    """One automation as `openclaw cron list --json` returns it."""
    schedule = {}
    if at is not None:
        schedule = {"kind": "at", "at": at}
    elif expr is not None:
        schedule = {"kind": "cron", "expr": expr, **({"tz": tz} if tz else {})}
    payload = {"kind": "agentTurn"}
    if message is not None:
        payload["message"] = message
    if model is not None:
        payload["model"] = model
    return {"id": jid or f"id-{name}", "name": name, "enabled": enabled,
            "sessionTarget": "isolated", "schedule": schedule, "payload": payload,
            "delivery": {"mode": "none"}}


class Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class FakeScheduler:
    """`node /app/openclaw.mjs cron ...` against an in-memory job list."""

    def __init__(self, rows=(), fail=None, listing=None):
        self.rows = list(rows)
        self.fail = fail or (lambda argv: 0)
        self.listing = listing
        self.calls = []

    def __call__(self, argv):
        assert argv[:3] == ["node", "/app/openclaw.mjs", "cron"], argv
        self.calls.append(argv)
        if argv[3] == "list":
            stdout = self.listing if self.listing is not None else json.dumps(
                {"jobs": self.rows, "total": len(self.rows), "hasMore": False})
            return Proc(0, stdout)
        rc = self.fail(argv)
        return Proc(rc, "", "boom" if rc else "")

    @property
    def writes(self):
        return [c[3:] for c in self.calls if c[3] != "list"]

    def backend(self):
        return backend_mod.CronBackend(self)


class TestListing:
    def test_lists_disabled_jobs_too(self):
        sched = FakeScheduler([row("pt-daily-edition", enabled=False)])
        jobs = sched.backend().list()
        assert sched.calls == [["node", "/app/openclaw.mjs", "cron", "list", "--all", "--json"]]
        assert [(j.name, j.enabled) for j in jobs] == [("pt-daily-edition", False)]

    @pytest.mark.parametrize("listing", ["garbage", json.dumps({"nope": []}),
                                         json.dumps({"jobs": [{"name": "no id"}]}),
                                         json.dumps({"jobs": "x"})])
    def test_unreadable_listing_aborts(self, listing):
        with pytest.raises(SystemExit, match="refusing to register"):
            FakeScheduler(listing=listing).backend().list()

    def test_truncated_listing_aborts(self):
        listing = json.dumps({"jobs": [], "total": 250, "hasMore": True})
        with pytest.raises(SystemExit, match="truncated"):
            FakeScheduler(listing=listing).backend().list()

    def test_failed_listing_aborts(self):
        def runner(argv):
            return Proc(1, "", "gateway unreachable")
        with pytest.raises(SystemExit, match="could not list"):
            backend_mod.CronBackend(runner).list()

    def test_only_pt_jobs_are_managed(self):
        jobs = FakeScheduler([row("heartbeat-main"), row("pt-daily-edition"),
                              row("Memory Dreaming Promotion")]).backend().list()
        assert list(crons.registered_jobs(jobs)) == ["pt-daily-edition"]

    def test_a_managed_name_registered_twice_is_refused(self):
        jobs = FakeScheduler([row("pt-daily-edition", jid="a"),
                              row("pt-daily-edition", jid="b")]).backend().list()
        with pytest.raises(SystemExit, match="registered twice"):
            crons.registered_jobs(jobs)

    def test_on_demand_copies_are_not_managed_by_name(self):
        jobs = FakeScheduler([row(crons.NOW_NAME, jid="a"),
                              row(crons.NOW_NAME, jid="b")]).backend().list()
        assert crons.registered_jobs(jobs) == {}


class TestLoadOwnerZone:
    def test_names_the_owner_zone(self, tmp_path):
        assert crons.load_owner_zone(write_config(tmp_path)) == TZ

    def test_blank_owner_timezone_refuses(self, tmp_path):
        blank_tz_config = {**CONFIG, "owner": {"timezone": ""}}
        path = write_config(tmp_path, config=blank_tz_config)
        with pytest.raises(SystemExit, match="blank owner.timezone"):
            crons.load_owner_zone(path)

    def test_missing_config_refuses(self, tmp_path):
        with pytest.raises(SystemExit, match="missing"):
            crons.load_owner_zone(tmp_path / "nope.json")


class TestDesiredJobs:
    def test_one_job_per_active_subscription(self, tmp_path):
        path = write_config(tmp_path)
        topics = [topic("t_9f2a"), topic("t_0c11")]
        jobs = crons.desired_jobs(topics, "07:00", TZ)
        assert [j["name"] for j in jobs] == [
            crons.DAILY_NAME,
            "pt-subscription-t_9f2a", "pt-subscription-t_0c11"]
        subs = [j for j in jobs if j["name"].startswith("pt-subscription-")]
        assert all(j["schedule"] == "0 7 * * *" for j in subs)
        assert all(j["tz"] == TZ for j in jobs)
        assert all("deliver" not in j for j in jobs)
        assert path.name == "config.json"  # config untouched

    def test_early_extra_slot_clamps_its_lead_instead_of_refusing(self):
        # The main paper's 40-minute lead must not abort registration for a
        # slot at 00:20: that slot starts at midnight, not the evening before.
        jobs = crons.desired_jobs(
            [topic("t_9f2a", kind="section", deliver_at="12:30")], "07:00", TZ, lead_minutes=40, extra_hours=["00:20"])
        by_name = {j["name"]: j["schedule"] for j in jobs}
        assert by_name[crons.DAILY_NAME] == "20 6 * * *"
        assert by_name[f"{crons.DAILY_NAME}-2"] == "0 0 * * *"
        assert by_name[crons.paper_job_name("12:30")] == "50 11 * * *"

    def test_lead_clamps_to_owner_midnight(self):
        # The owner's 00:20 with a 40-minute lead starts at owner midnight,
        # not the evening before; the owner's 10:30 keeps the full lead.
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section", deliver_at="14:30")], "00:20",
            "America/Sao_Paulo", 40, extra_hours=["10:30"],
        )
        assert jobs[0]["schedule"] == "0 0 * * *"
        assert jobs[1]["schedule"] == "50 9 * * *"
        assert jobs[2]["schedule"] == "50 13 * * *"
        assert {j["tz"] for j in jobs} == {"America/Sao_Paulo"}

    def test_every_cron_job_fires_on_the_owner_clock(self):
        # The owner's 07:00 in Tokyo is registered as 07:00 with --tz
        # Asia/Tokyo: the scheduler converts, daylight saving included.
        jobs = crons.desired_jobs(
            [topic("t_9f2a"), topic("t_1", kind="section", deliver_at="12:00")], "07:00",
            "Asia/Tokyo")
        by_name = {j["name"]: j for j in jobs}
        daily = by_name[crons.DAILY_NAME]
        assert (daily["schedule"], daily["tz"]) == ("0 7 * * *", "Asia/Tokyo")
        assert "--hold-until 07:00 " in daily["prompt"]
        assert by_name["pt-subscription-t_9f2a"]["schedule"] == "0 7 * * *"
        paper = by_name[crons.paper_job_name("12:00")]
        assert "--deliver-at 12:00" in paper["prompt"]
        assert (paper["schedule"], paper["tz"]) == ("0 12 * * *", "Asia/Tokyo")

    def test_one_off_is_a_one_shot_at_its_own_offset(self):
        oneoff = {**topic("t_0c11", kind="one_off", depth="quick"), "scheduled_for": FUTURE}
        (job,) = [j for j in crons.desired_jobs([oneoff], "07:00", TZ) if j["name"] == "pt-oneoff-t_0c11"]
        assert (job["schedule"], job["tz"]) == (FUTURE, None)

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
            [topic("t_9f2a", status="cancelled")], "07:00", TZ)
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
        jobs = crons.desired_jobs([oneoff], "07:00", TZ)
        assert [j["schedule"] for j in jobs if j["name"] == "pt-oneoff-t_0c11"] == fires_at

    def test_running_subscription_still_has_its_job(self):
        jobs = crons.desired_jobs([topic("t_9f2a", status="running")], "07:00", TZ)
        assert [j["name"] for j in jobs] == [crons.DAILY_NAME, "pt-subscription-t_9f2a"]

    def test_hour_derived_without_leading_zero(self):
        jobs = crons.desired_jobs([topic("t_9f2a")], "23:00", TZ)
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


class TestArgv:
    def test_cron_job_is_an_isolated_undelivered_turn_in_the_owner_zone(self):
        jobs = crons.desired_jobs([topic("t_9f2a")], "07:00", TZ)
        sub = next(j for j in jobs if j["name"] == "pt-subscription-t_9f2a")
        argv = backend_mod.CronBackend().create_argv(sub)
        assert argv[:4] == ["node", "/app/openclaw.mjs", "cron", "add"]
        assert argv[argv.index("--name") + 1] == "pt-subscription-t_9f2a"
        assert argv[argv.index("--cron") + 1] == "0 7 * * *"
        assert argv[argv.index("--tz") + 1] == TZ
        assert argv[argv.index("--session") + 1] == "isolated"
        assert argv[argv.index("--message") + 1] == sub["prompt"]
        assert argv[argv.index("--model") + 1] == "plow/z-ai/glm-5.2"
        assert "--no-deliver" in argv and "--exact" in argv and "--json" in argv
        assert "--announce" not in argv and "--token" not in argv

    def test_one_shot_uses_at_without_a_zone(self):
        oneoff = {**topic("t_0c11", kind="one_off", depth="quick"), "scheduled_for": FUTURE}
        job = crons.oneoff_job(oneoff)
        argv = backend_mod.CronBackend().create_argv(job)
        assert argv[argv.index("--at") + 1] == FUTURE
        assert "--cron" not in argv and "--tz" not in argv

    def test_edit_patches_the_job_by_id(self):
        daily = crons.desired_jobs([topic("t_9f2a")], "07:00", TZ)[0]
        argv = backend_mod.CronBackend().edit_argv("abc", daily)
        assert argv[:5] == ["node", "/app/openclaw.mjs", "cron", "edit", "abc"]
        assert argv[argv.index("--cron") + 1] == daily["schedule"]
        assert argv[argv.index("--tz") + 1] == TZ
        assert argv[argv.index("--message") + 1] == daily["prompt"]
        assert "--no-deliver" in argv

    def test_remove_is_by_id(self):
        assert backend_mod.CronBackend().remove_argv("abc") == [
            "node", "/app/openclaw.mjs", "cron", "rm", "abc", "--json"]


def run_main(tmp_path, monkeypatch, topics_list, sched, argv=None, config=CONFIG, env=None):
    pt_home = tmp_path / "pt"
    pt_home.mkdir(exist_ok=True)
    (pt_home / "config.json").write_text(json.dumps(config))
    (pt_home / "topics.json").write_text(json.dumps({"topics": topics_list}))
    monkeypatch.setenv("PT_HOME", str(pt_home))
    monkeypatch.chdir(tmp_path)
    return crons.main(argv, backend=sched.backend(), config_path=pt_home / "config.json",
                      env=env if env is not None else {})


def registered_like_spec(topics_list, **overrides):
    """Rows exactly as a previous run of this script would have left them."""
    return [row(j["name"], expr=j["schedule"] if j["tz"] else None,
                at=None if j["tz"] else j["schedule"], tz=j["tz"], message=j["prompt"],
                model="plow/z-ai/glm-5.2", **overrides)
            for j in crons.desired_jobs(topics_list, "07:00", TZ)]


class TestMain:
    def test_needs_no_container_tz(self, tmp_path, monkeypatch):
        sched = FakeScheduler()
        assert run_main(tmp_path, monkeypatch, [], sched, env={}) == 0
        assert [w[0] for w in sched.writes] == ["add"]

    def test_now_queues_the_main_papers_own_prompt_as_a_one_shot(
            self, tmp_path, monkeypatch, capsys):
        # "Send me the paper now" is the SAME job the 7am run fires. Measured
        # live: a variant of the recipe skipped the advisor, so an on-demand
        # paper came back with a gap card and one story.
        sched = FakeScheduler(registered_like_spec([]))
        rc = run_main(tmp_path, monkeypatch, [], sched, argv=["--now"])
        assert rc == 0
        (create,) = [w for w in sched.writes if crons.NOW_NAME in w]
        at = create[create.index("--at") + 1]
        assert "T" in at and at[-6] in "+-"  # an ISO instant with its offset
        assert create[create.index("--message") + 1] == crons.paper_prompt()
        assert "--no-deliver" in create
        assert "queued: pt-daily-edition-now" in capsys.readouterr().out

    @pytest.mark.parametrize("create_rc", [0, 1])
    def test_now_removes_the_previous_one_shot_only_after_queueing_its_successor(
            self, tmp_path, monkeypatch, create_rc):
        # A failed create must not cancel a copy the owner was already promised.
        def fail(argv):
            return create_rc if argv[3] == "add" and crons.NOW_NAME in argv else 0
        rows = registered_like_spec([]) + [row(crons.NOW_NAME, jid="old123", at=FUTURE)]
        sched = FakeScheduler(rows, fail=fail)
        if create_rc:
            with pytest.raises(SystemExit, match="could not queue"):
                run_main(tmp_path, monkeypatch, [], sched, argv=["--now"])
            assert not any(w[0] == "rm" for w in sched.writes)
        else:
            run_main(tmp_path, monkeypatch, [], sched, argv=["--now"])
            assert [w[:2] for w in sched.writes] == [["add", "--name"], ["rm", "old123"]]

    def test_rebuild_recreates_a_pending_one_offs_job(self, tmp_path, monkeypatch):
        # A fresh state volume has no jobs: a one-off the owner was promised
        # must come back from topics.json like any subscription does.
        oneoff = {**topic("t_0c11", kind="one_off", depth="quick"), "scheduled_for": FUTURE}
        sched = FakeScheduler(registered_like_spec([]))
        run_main(tmp_path, monkeypatch, [oneoff], sched)
        (create,) = [w for w in sched.writes if "pt-oneoff-t_0c11" in w]
        assert create[create.index("--at") + 1] == FUTURE
        assert "topic t_0c11 now (depth quick)" in create[create.index("--message") + 1]

    def test_registration_never_sweeps_a_queued_copy(self, tmp_path, monkeypatch):
        sched = FakeScheduler(registered_like_spec([]) + [row(crons.NOW_NAME, at=FUTURE)])
        run_main(tmp_path, monkeypatch, [], sched)
        assert sched.writes == []

    def test_registers_missing_subscription(self, tmp_path, monkeypatch):
        sched = FakeScheduler(registered_like_spec([]))
        assert run_main(tmp_path, monkeypatch, [topic("t_9f2a")], sched) == 0
        assert [w[0] for w in sched.writes] == ["add"]
        assert "pt-subscription-t_9f2a" in sched.writes[0]

    def test_idempotent_run_skips_present(self, tmp_path, monkeypatch):
        topics_list = [topic("t_9f2a")]
        sched = FakeScheduler(registered_like_spec(topics_list))
        assert run_main(tmp_path, monkeypatch, topics_list, sched) == 0
        assert sched.writes == []  # nothing created, edited or removed

    def test_removes_stale_by_id_and_creates_missing(self, tmp_path, monkeypatch):
        sched = FakeScheduler(registered_like_spec([]) + [row("pt-subscription-t_ffff", jid="orphan")])
        assert run_main(tmp_path, monkeypatch, [topic("t_0c11")], sched) == 0
        assert ["rm", "orphan", "--json"] in sched.writes
        assert any(w[0] == "add" and "pt-subscription-t_0c11" in w for w in sched.writes)

    def test_foreign_jobs_are_never_touched(self, tmp_path, monkeypatch):
        sched = FakeScheduler(registered_like_spec([]) + [row("heartbeat-main", expr="*/30 * * * *")])
        run_main(tmp_path, monkeypatch, [], sched)
        assert sched.writes == []

    def test_disabled_job_is_left_alone_and_named(self, tmp_path, monkeypatch, capsys):
        sched = FakeScheduler(registered_like_spec([], enabled=False))
        with pytest.raises(SystemExit, match="DISABLED"):
            run_main(tmp_path, monkeypatch, [], sched)
        assert sched.writes == []  # not duplicated, not edited
        assert "cron enable id-pt-daily-edition" in capsys.readouterr().out

    def test_unreadable_listing_writes_nothing(self, tmp_path, monkeypatch):
        sched = FakeScheduler(listing="not json")
        with pytest.raises(SystemExit, match="refusing to register"):
            run_main(tmp_path, monkeypatch, [topic("t_9f2a")], sched)
        assert sched.writes == []

    def test_failed_create_fails_loud(self, tmp_path, monkeypatch):
        sched = FakeScheduler(fail=lambda argv: 1)
        with pytest.raises(SystemExit, match="could not register"):
            run_main(tmp_path, monkeypatch, [topic("t_9f2a")], sched)


class TestDailySchedule:
    def test_default_lead_is_zero(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section")], "07:00", TZ)
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
        job = crons.subscription_job(topic("t_9f2a"), "10:25", TZ)
        assert job["schedule"] == "25 10 * * *"

    def test_whole_hour_still_works(self):
        job = crons.subscription_job(topic("t_9f2a"), "07:00", TZ)
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
            [topic("t_1", kind="section")], "03:00", TZ,
            45, extra_hours=["10:30"],
        )
        names = [j["name"] for j in jobs]
        assert names == ["pt-daily-edition", "pt-daily-edition-2"]
        # Each slot gets its own lead-time subtraction -- 10:30 minus 45m.
        assert jobs[1]["schedule"] == "45 9 * * *"
        assert jobs[1]["tz"] == TZ

    def test_extra_job_prompt_shares_the_workspace_lock_and_has_the_pdf_leg(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section")], "03:00", TZ, 45, extra_hours=["10:30"],
        )
        prompt = jobs[1]["prompt"]
        assert "paper-workspace-<today's date" in prompt
        assert "post_to_chat.py" in prompt
        assert "NO_REPLY" not in prompt

    def test_no_extra_hours_is_unchanged(self):
        jobs = crons.desired_jobs([topic("t_1", kind="section")], "03:00", TZ, 45)
        assert [j["name"] for j in jobs] == ["pt-daily-edition"]

    @pytest.mark.parametrize("extra,section_hour", [
        (["09:00"], None),
        ([], "09:00"),
    ])
    def test_papers_less_than_three_hours_apart_are_refused(self, extra, section_hour):
        topics = [topic("t_1", kind="section", deliver_at=section_hour)] if section_hour else []

        with pytest.raises(SystemExit, match="paper times 07:00 and 09:00 are less than 180 minutes apart"):
            crons.desired_jobs(topics, "07:00", TZ, 0, extra_hours=extra)

    def test_multiple_extra_hours_are_numbered_in_order(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section")], "03:00", TZ, 45,
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
            "07:00", TZ, 0,
        )
        names = [j["name"] for j in jobs]
        assert names == [
            "pt-daily-edition", "pt-paper-1230", "pt-paper-1800",
        ]
        assert jobs[1]["schedule"] == "30 12 * * *"
        assert jobs[2]["schedule"] == "0 18 * * *"
        assert "deliver_at is 12:30" in jobs[1]["prompt"]
        assert "paper-workspace-<today's date" in jobs[1]["prompt"]
        assert "NO_REPLY" not in jobs[1]["prompt"]

    def test_deliver_at_equal_to_main_hour_rides_the_daily_job(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section", deliver_at="07:00")],
            "07:00", TZ, 0,
        )
        assert [j["name"] for j in jobs] == ["pt-daily-edition"]

    def test_cancelled_timed_section_is_not_a_paper(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section", deliver_at="12:30", status="cancelled")],
            "07:00", TZ, 0,
        )
        assert [j["name"] for j in jobs] == ["pt-daily-edition"]

    def test_papers_sit_between_extra_hours_and_subscriptions(self):
        jobs = crons.desired_jobs(
            [
                topic("t_1", kind="section", deliver_at="13:30"),
                topic("t_9f2a"),
            ],
            "07:00", TZ, 0, extra_hours=["10:30"],
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
            [topic("t_1", kind="section", status="pending")], "07:00", TZ, 45)
        assert jobs[0]["name"] == crons.DAILY_NAME
        assert jobs[0]["schedule"] == "15 6 * * *"
        assert jobs[0]["tz"] == TZ

    def test_included_when_an_assignment_is_due(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="assignment", status="pending", run_on="2026-09-11")],
            "07:00", TZ, 45)
        assert [j["name"] for j in jobs] == [crons.DAILY_NAME]

    def test_present_even_without_news_sections(self):
        jobs = crons.desired_jobs([topic("t_9f2a")], "07:00", TZ, 45)
        assert [j["name"] for j in jobs] == [crons.DAILY_NAME, "pt-subscription-t_9f2a"]

    def test_daily_precedes_subscriptions(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section"), topic("t_9f2a")], "07:00", TZ, 45)
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
    JOB = {"name": "pt-daily-edition", "schedule": "15 6 * * *", "tz": TZ, "prompt": "same"}

    def spec(self, **fields):
        return backend_mod.Job(row("pt-daily-edition", **fields)).spec

    def test_schedule_drift_detected(self):
        assert crons.job_drift(self.JOB, self.spec(expr="0 7 * * *", tz=TZ)) is True

    def test_zone_drift_detected(self):
        # The owner moved: same hour, another zone.
        assert crons.job_drift(self.JOB, self.spec(expr="15 6 * * *", tz="Europe/Lisbon")) is True

    def test_prompt_drift_detected(self):
        assert crons.job_drift(self.JOB, self.spec(expr="15 6 * * *", tz=TZ, message="old")) is True

    def test_model_drift_detected(self):
        assert crons.job_drift(self.JOB, self.spec(expr="15 6 * * *", tz=TZ, model="plow/anthropic/claude-opus-5")) is True

    def test_matching_spec_is_not_drift(self):
        spec = self.spec(expr="15 6 * * *", tz=TZ, message="same", model="plow/z-ai/glm-5.2")
        assert crons.job_drift(self.JOB, spec) is False

    def test_absent_fields_are_not_drift(self):
        assert crons.job_drift(self.JOB, self.spec()) is False

    def test_one_shot_compared_as_an_instant(self):
        # The scheduler normalizes --at to UTC; the same instant is no drift.
        job = {"name": "pt-oneoff-t_0c11", "schedule": "2026-09-25T09:00:00-03:00", "tz": None, "prompt": "p"}
        assert crons.job_drift(job, self.spec(at="2026-09-25T12:00:00.000Z")) is False
        assert crons.job_drift(job, self.spec(at="2026-09-25T13:00:00.000Z")) is True


class TestDriftMain:
    def test_drifted_job_edited_in_place(self, tmp_path, monkeypatch):
        rows = registered_like_spec([topic("t_1", kind="section")])
        rows[0]["schedule"]["expr"] = "15 6 * * *"
        sched = FakeScheduler(rows)
        assert run_main(tmp_path, monkeypatch, [topic("t_1", kind="section")], sched) == 0
        assert [w[:2] for w in sched.writes] == [["edit", "id-pt-daily-edition"]]
        edit = sched.writes[0]
        assert edit[edit.index("--cron") + 1] == "0 7 * * *"

    def test_owner_zone_change_edits_every_cron_job(self, tmp_path, monkeypatch):
        topics_list = [topic("t_9f2a")]
        sched = FakeScheduler(registered_like_spec(topics_list))
        moved = {**CONFIG, "owner": {"timezone": "Europe/Lisbon"}}
        run_main(tmp_path, monkeypatch, topics_list, sched, config=moved)
        assert sorted(w[1] for w in sched.writes) == ["id-pt-daily-edition", "id-pt-subscription-t_9f2a"]
        assert all(w[0] == "edit" and w[w.index("--tz") + 1] == "Europe/Lisbon" for w in sched.writes)

    def test_failed_edit_fails_loud(self, tmp_path, monkeypatch):
        rows = registered_like_spec([])
        rows[0]["schedule"]["expr"] = "15 6 * * *"
        sched = FakeScheduler(rows, fail=lambda argv: 1)
        with pytest.raises(SystemExit, match="could not update drifted job"):
            run_main(tmp_path, monkeypatch, [], sched)
        assert not any(w[0] == "rm" for w in sched.writes)

    def test_daily_kept_while_only_a_subscription_lives(self, tmp_path, monkeypatch):
        topics_list = [topic("t_9f2a")]
        sched = FakeScheduler(registered_like_spec(topics_list))
        run_main(tmp_path, monkeypatch, topics_list, sched)
        assert not any(w[0] == "rm" for w in sched.writes)


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
        jobs = crons.desired_jobs([], "07:00", TZ)
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
        jobs = crons.desired_jobs([topic("t_1", kind="section")], "07:00", TZ, 40)
        assert "--stale-minutes 280" in jobs[0]["prompt"]

    def test_paper_job_holds_until_its_hour(self):
        jobs = crons.desired_jobs(
            [topic("t_sec", kind="section", deliver_at="12:00")],
            "07:00", TZ,
        )
        paper = next(j for j in jobs if j["name"] == "pt-paper-1200")
        assert "--hold-until 12:00" in paper["prompt"]
        assert "--stale-minutes 240" in paper["prompt"]

    def test_a_scheduled_paper_waits_out_a_fresh_holder_before_skipping(self):
        # An on-demand paper ("manda o jornal agora") holds the same workspace
        # lock for its whole run (~34 min measured live). A scheduled paper that
        # fires meanwhile waits two 20-minute rounds -- each under OpenClaw's
        # 30-minute exec timeout -- and only then gives the day up.
        wait = f"--wait-seconds {crons.HELD_LOCK_WAIT_SECONDS}"
        assert crons.HELD_LOCK_WAIT_SECONDS == 1200
        jobs = crons.desired_jobs(
            [topic("t_sec", kind="section", deliver_at="12:00")], "07:00", TZ, 150, extra_hours=["18:00"],
        )
        for job in jobs:
            if job["name"].startswith(("pt-daily-edition", "pt-paper-")):
                assert wait in job["prompt"], job["name"]
                assert "run the same acquire once more" in job["prompt"], job["name"]

    def test_the_on_demand_copy_never_waits_on_the_lock(self):
        p = crons.paper_prompt(lead_minutes=150)
        assert "--wait-seconds" not in p
        assert "run the same acquire once more" not in p

    def test_extra_slot_holds_until_its_hour(self):
        jobs = crons.desired_jobs(
            [topic("t_1", kind="section")], "03:00", TZ, 45, extra_hours=["10:30"],
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
        # Jobs have no delivery arm (--no-deliver): the final text goes nowhere.
        assert "NO_REPLY" not in p and "--deliver " not in p

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
