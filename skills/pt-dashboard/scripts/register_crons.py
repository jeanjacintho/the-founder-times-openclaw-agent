#!/usr/bin/env python3
"""Register the Founder Times' crons, idempotently, from the topic store.

Why this exists at all. The scheduler keeps its jobs in the gateway's state
volume; a fresh volume has none, and nothing else replays them. Keeping the
spec here, derived from pt/topics.json (the one record of what the owner
asked to be watched), means "set up the plow times crons" replays a reviewed
derivation instead of improvising schedules from a sentence. The spec is
data-driven rather than fixed: the topic list changes.

The spec (design doc §3.6 and the personalized-paper plan §3.3/§6):

  pt-daily-edition       <min> <hour> * * *        one job; exists while
                         computed as                setup can register
                         delivery.hour -
                         lead_minutes (never
                         before midnight)
  pt-daily-edition-<n>   same, extra_hours         reprint of the MAIN paper
                         (n ≥ 2)                    (unscoped sections), not
                                                    a different roster
  pt-paper-HHMM          same computation          one job per distinct
                         against a section's        section deliver_at that
                         deliver_at                 is not delivery.hour
  pt-subscription-<id>   0 <delivery.hour> * * *   one per subscription topic
                                                   not yet cancelled
  pt-oneoff-<id>         one-shot at the topic's   one per pending one-off
                         scheduled_for             still ahead; swept once
                                                   delivered
  pt-daily-edition-now   one-shot, a minute out    --now: the main paper on
                                                   demand, same prompt, no hold

Every cron job is registered with `--tz owner.timezone`: every stored hour --
delivery.hour, extra_hours, a section's deliver_at -- is the owner's wall
clock, and the scheduler fires on it directly, daylight saving included.
post_to_chat.py's --hold-until waits on the same zone. Each job is an agent
turn in an isolated session with delivery `none`; the paper reaches chat
through post_to_chat.py.

This script therefore CREATES missing jobs and REMOVES pt-* jobs whose
topic is gone -- cancelled, delivered one-offs, or names with no topic
behind them. It never touches a job whose name does not start with pt-:
those are not this agent's to manage (OpenClaw keeps its own jobs, such as
its heartbeat, in the same list).

It also RECONCILES drift, which create-if-missing alone does not: a job
that is registered with a different schedule, zone, prompt or model than
the spec calls for is updated in place with `cron edit`. Drift is only
judged on a field the scheduler reported; a missing field is left alone
rather than edited on a guess. Never remove-then-create a drifted job: if
create failed after remove, the morning paper had no job until someone
reran the script.

One refusal is the point of the script: an unreadable, partial or
unexpected job listing aborts. Never read "I could not tell what is
registered" as "nothing is" -- that re-registers every job and duplicates
all of them.

It runs INSIDE the container, from a turn: exec inherits the gateway token
the scheduler CLI needs.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_SKILLS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..")
sys.path[:0] = [os.path.join(_SKILLS, "pt-intake", "scripts"), os.path.join(_SKILLS, "pt-shared", "scripts")]
from record_owner_language import _write_json  # noqa: E402 -- the config's atomic writer
from pt_paths import config_file, script  # noqa: E402
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from cron_backend import MODEL, OPENCLAW, CronBackend  # noqa: E402 -- sibling module

CONFIG_FILE = str(config_file())
# The only job names this spec owns. Pinned as a fullmatch so a name that
# does not parse is never interpreted, and a half-matching id never removes
# a job (see stale_names).
_JOB_NAME_RE = re.compile(r"^pt-(?P<kind>subscription|oneoff)-(?P<tid>t_[0-9a-f]{4})$")
# The one daily-paper job; no topic id because it is the whole paper, not a
# topic. Owned and swept by name, exactly like the id-borne jobs above.
DAILY_NAME = "pt-daily-edition"
# A second (or third, ...) full-paper delivery time, from
# delivery.extra_hours -- same paper, same sections, re-researched and
# re-delivered at another hour of the same day. Numbered from 2 so the
# canonical DAILY_NAME reads as "the" edition and these read as its
# reruns, matching the lock-name convention (daily2-<date>, daily3-<date>)
# a hand-registered job already used before this existed as a real spec.
_EXTRA_DAILY_RE = re.compile(r"^pt-daily-edition-(?P<n>[2-9]\d*)$")
# A focused paper at a section's deliver_at, named from the hour so two
# sections at 12:30 share one job and a dropped hour is sweepable by name.
_PAPER_RE = re.compile(r"^pt-paper-(?P<hhmm>(?:[01]\d|2[0-3])[0-5]\d)$")
# The on-demand copy (--now): a one-shot the sweep below never removes, so
# a queued paper survives a registration run; the next --now replaces it.
NOW_NAME = "pt-daily-edition-now"
WORKSPACE_LOCK = "paper-workspace"
DEFAULT_LEAD_MINUTES = 0
# Every acquirer of a lock uses one lifetime: the run itself plus
# delivery.lead_minutes, since a scheduled run holds the lock through its early
# start and the held POST. Every paper shares the workspace lock, so a smaller
# number could call the scheduled run dead and start a competing paper.
STALE_RUN_MINUTES = 240
# A scheduled paper that finds the workspace held (an on-demand copy runs its
# whole ~35-minute paper under the lock) waits two rounds of this before giving
# the day up: ~40 minutes, inside the hold-until window, each round under
# OpenClaw's 30-minute exec timeout. The on-demand copy never waits.
HELD_LOCK_WAIT_SECONDS = 1200
# The priority desk's floor: with less than this left before delivery, a fresh
# three-generation tournament cannot finish (measured ~35-50 min) before the
# render and print still to follow. A delivery hour near midnight clamps the
# lead below it and nothing refuses that, so the prompt states the window and
# the desk writes its own reason instead of starting a tournament it cannot end.
MIN_TOURNAMENT_MINUTES = 50

# One topic's own edition: a subscription's nightly run or a one-off.
TOPIC_PROMPT = (
    "Run pt-research on topic {tid} now (depth {depth}), then pt-edition for it, "
    "delivering with post_to_chat.py per pt-edition/SKILL.md step 2."
)


def paper_prompt(hold_until=None, lead_minutes=0, focus=None):
    """The one run prompt every paper is built from, scheduled or on demand.

    focus=None is the MAIN paper: every active section with no deliver_at
    (or deliver_at equal to delivery.hour) and every assignment due today.
    focus="HH:MM" is the focused paper for sections booked at that hour.
    Every paper shares one workspace lock because their desk and topic
    scratch is shared. A scheduled paper reuses today's accepted advisor
    checkpoint when one exists, else runs the tournament.

    hold_until is the send clock (delivery.hour / an extra or focused hour).
    The job may start earlier via lead_minutes; POST must still wait. The
    on-demand copy (--now) passes none, posts when done, and never waits
    ~150 minutes on a tournament: it reuses the newest accepted checkpoint
    of any date, printed with its as-of date, and runs the tournament only
    when none has ever been accepted.

    The prompt carries only what the run cannot read from its skills: the
    lock, the roster, the advice rule and the send clock. Delivery, print
    and topic finalization are pt-edition step 2's, never restated here.
    """
    if focus is None:
        title, check = "the daily edition", "--deliver-at main --as-of <today's YYYY-MM-DD>"
        roster = (
            "every active news section with no deliver_at (or deliver_at "
            "equal to delivery.hour in pt/config.json — skip sections that belong "
            "to another paper hour) and every assignment with run_on <= today"
        )
    else:
        title, check = f"the {focus} paper", f"--deliver-at {focus}"
        roster = (
            f"ONLY active news sections whose deliver_at is {focus} (read topics.json; "
            f"do not research unscoped sections, sections of another hour, or assignments)"
        )
    hold = (
        f" with --hold-until {hold_until} so chat waits for that clock "
        f"(if that hour has already passed, post immediately; never wait until tomorrow)"
        if hold_until else ""
    )
    lock = script("pt-shared", "run_lock.py")
    advice = (
        "reuse today's accepted checkpoint in run/desk-priority/tournament.json when "
        f"there is one, else run the tournament -- this job starts {lead_minutes} minutes "
        f"before {hold_until} (delivery.lead_minutes, clamped so it never starts before "
        f"midnight); once the lock is yours, run {script('pt-shared', 'owner_time.py')} "
        f"minutes-until {hold_until} and, under {MIN_TOURNAMENT_MINUTES} minutes, write the "
        f"desk's own unavailable reason per pt-priority/SKILL.md instead of starting one"
        if hold_until else
        "reuse the newest accepted checkpoint in run/desk-priority/tournament.json whatever "
        "its date -- an older one prints with \"as_of\" per pt-edition -- and run the "
        "tournament only if none has ever been accepted"
    )
    wait = f" --wait-seconds {HELD_LOCK_WAIT_SECONDS}" if hold_until else ""
    held = (
        "run the same acquire once more; if that is also 'held', another paper owns "
        "the workspace -- stop"
        if hold_until else "another paper owns the workspace -- stop"
    )
    return (
        f"Run {title} now, in one session. First run {lock} acquire "
        f"--name {WORKSPACE_LOCK}-<today's date in the owner's "
        f"zone> --stale-minutes {STALE_RUN_MINUTES + lead_minutes}{wait}; if its output is 'held', "
        f"{held}. Then "
        f"/opt/plow/skills/pt-shared/scripts/prepare_daily_run.py --preserve-priority "
        f"(it archives prior scratch after the lock; do not inspect or reuse old run files). Then "
        f"/opt/plow/skills/pt-intake/scripts/topics.py reopen-sections "
        f"(delivered sections are yesterday's paper, not a skip). Run "
        f"/opt/plow/skills/pt-intake/scripts/topics.py check-paper {check}. "
        f"If it refuses, repeat its named roster, run {lock} "
        f"release --name the same {WORKSPACE_LOCK}-<date>, and stop before research. "
        f"Then run pt-research: first the priority desk exactly as "
        f"pt-research/references/desks.md says ({advice}), "
        f"then every other standing desk it lists, in its order, then {roster}. "
        f"Then run pt-edition for the batch, delivering with post_to_chat.py "
        f"per pt-edition/SKILL.md step 2{hold}. "
        f"Release the lock with {lock} release --name the same {WORKSPACE_LOCK}-<date>."
    )


def load_owner_zone(config_path=CONFIG_FILE):
    """owner.timezone, or refuse: every schedule here is written against it."""
    path = pathlib.Path(config_path)
    try:
        config = json.loads(path.read_text())
        owner = config["owner"]["timezone"]
    except FileNotFoundError:
        raise SystemExit(
            f"refusing to register: {path} is missing. pt-setup writes it; "
            "its owner.timezone is what every schedule here is written against."
        ) from None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(
            f"refusing to register: could not read owner.timezone from {path} "
            f"({exc!r})."
        ) from exc
    if not str(owner or "").strip():
        raise SystemExit(
            f"refusing to register: {path} has a blank owner.timezone."
        )
    return owner


def adopt_owner_clock(owner_tz, legacy_tz, config_path=CONFIG_FILE):
    """Retire delivery.local_hour, left by an older setup that stored
    delivery.hour on the previous runtime's container clock (legacy_tz, that
    install's TZ). With one zone that hour already is the owner's; across two
    zones it is not recoverable without guessing through offsets.
    """
    path = pathlib.Path(config_path)
    config = json.loads(path.read_text())
    if "local_hour" not in config["delivery"]:
        return
    if owner_tz != legacy_tz:
        raise SystemExit(
            f"refusing to register: {path} predates owner-clock hours and its times "
            f"are on the old container clock ({legacy_tz}), not the owner's "
            f"({owner_tz}). Ask the owner for their delivery time, extra hours and "
            "paper times again, write them as their own clock, remove "
            "delivery.local_hour, and re-run.")
    del config["delivery"]["local_hour"]
    _write_json(path, config)


def load_delivery_hour(config_path=CONFIG_FILE):
    """delivery.hour from pt/config.json -- its exact 'HH:MM' shape is the
    gate's contract; both parts feed the schedule."""
    path = pathlib.Path(config_path)
    try:
        config = json.loads(path.read_text())
        return str(config["delivery"]["hour"])
    except FileNotFoundError:
        raise SystemExit(
            f"refusing to register: {path} is missing -- pt-setup owns it"
        ) from None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"refusing to register: malformed {path} ({exc!r}).") from exc


def load_extra_hours(config_path=CONFIG_FILE):
    """delivery.extra_hours from pt/config.json -- additional full-paper
    delivery times the same day, each "HH:MM" like delivery.hour itself.

    Optional and defaults to empty: an install with one delivery time a day
    (the common case) has no extra_hours key at all, and a schedule that
    refused to compute without it would strand a working agent. The gate
    validates each entry's shape when the key is present; this just reads
    it back, in order (order is the slot numbering -- pt-daily-edition-2 is
    always extra_hours[0]).
    """
    path = pathlib.Path(config_path)
    try:
        config = json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(
            f"refusing to register: {path} is missing -- pt-setup owns it"
        ) from None
    except (OSError, ValueError) as exc:
        raise SystemExit(f"refusing to register: malformed {path} ({exc!r}).") from exc
    hours = config.get("delivery", {}).get("extra_hours") or []
    if not isinstance(hours, list) or not all(isinstance(h, str) for h in hours):
        raise SystemExit(
            f"refusing to register: {path} has delivery.extra_hours={hours!r}; "
            "it must be a list of \"HH:MM\" strings."
        )
    return hours


def load_lead_minutes(config_path=CONFIG_FILE):
    """delivery.lead_minutes from pt/config.json, defaulting to 0.

    The key is optional on purpose (the gate only validates it when present):
    an install written before the personalized paper existed has no
    lead_minutes, and a schedule that refuses to compute for it would strand
    a working agent. Absent means the default, not an error.
    """
    path = pathlib.Path(config_path)
    try:
        config = json.loads(path.read_text())
        raw = config.get("delivery", {}).get("lead_minutes", DEFAULT_LEAD_MINUTES)
    except FileNotFoundError:
        raise SystemExit(
            f"refusing to register: {path} is missing -- pt-setup owns it"
        ) from None
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        raise SystemExit(f"refusing to register: malformed {path} ({exc!r}).") from exc
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise SystemExit(
            f"refusing to register: {path} has delivery.lead_minutes={raw!r}; "
            "it must be a non-negative integer (minutes before delivery.hour)."
        )
    return raw


def _hour_minute(delivery_hour):
    """Parse a gate-shaped "HH:MM" into (hour, minute) ints."""
    hour_part, minute_part = delivery_hour.split(":")
    return int(hour_part), int(minute_part)


def _minutes(hhmm):
    hour, minute = _hour_minute(hhmm)
    return hour * 60 + minute


def _lead(hour, lead_minutes):
    """The lead for one owner-clock hour, clamped so the run never starts
    before midnight -- the run's lock and paper are dated in the owner's zone."""
    return min(lead_minutes, _minutes(hour))


def daily_schedule(delivery_hour, lead_minutes):
    """The daily paper's cron expression, on its delivery day.

    delivery.hour is any real "HH:MM" (the gate's contract). The lead is
    subtracted in minutes from the OWNER's chosen minute, not just the hour.
    A lead reaching back past midnight is refused: that run would fire the
    evening before and be the previous day's paper. Every job's schedule
    comes through here, so this is the one place that refuses it.
    """
    total = _minutes(delivery_hour) - lead_minutes
    if total < 0:
        raise SystemExit(
            f"refusing to register: delivery.lead_minutes={lead_minutes} would start "
            f"the {delivery_hour} run before midnight of its delivery day.")
    return f"{total % 60} {total // 60} * * *"


def daily_job(delivery_hour, lead_minutes, owner_tz, *, name=DAILY_NAME):
    """One full-paper delivery job -- the canonical slot, or an extra one."""
    return {
        "name": name,
        "schedule": daily_schedule(delivery_hour, lead_minutes),
        "tz": owner_tz,
        "prompt": paper_prompt(hold_until=delivery_hour, lead_minutes=lead_minutes),
    }


def paper_job_name(hour):
    """pt-paper-HHMM from a strict HH:MM (12:30 → pt-paper-1230)."""
    hh, mm = hour.split(":")
    return f"pt-paper-{hh}{mm}"


def paper_hour_from_name(name):
    match = _PAPER_RE.fullmatch(name)
    if match is None:
        return None
    hhmm = match.group("hhmm")
    return f"{hhmm[:2]}:{hhmm[2:]}"


def focused_paper_hours(topics, delivery_hour):
    """Distinct section deliver_at values that are not the main paper hour."""
    hours = []
    seen = set()
    for topic in topics:
        if topic.get("kind") != "section" or topic.get("status") == "cancelled":
            continue
        at = topic.get("deliver_at")
        if not at or at == delivery_hour or at in seen:
            continue
        seen.add(at)
        hours.append(at)
    return sorted(hours)


def require_workspace_spacing(hours):
    """Refuse paper starts whose shared-workspace windows can overlap."""
    minimum_minutes = 180
    for index, first in enumerate(hours):
        for second in hours[index + 1:]:
            distance = abs(_minutes(first) - _minutes(second))
            if min(distance, 24 * 60 - distance) < minimum_minutes:
                raise SystemExit(
                    f"refusing to register: paper times {first} and {second} are less than "
                    f"{minimum_minutes} minutes apart; their shared workspace can overlap."
                )


def paper_job(hour, lead_minutes, owner_tz):
    """One focused paper: desks plus sections whose deliver_at is this hour."""
    return {
        "name": paper_job_name(hour),
        "schedule": daily_schedule(hour, lead_minutes),
        "tz": owner_tz,
        "prompt": paper_prompt(hold_until=hour, lead_minutes=lead_minutes, focus=hour),
    }


def subscription_job(topic, delivery_hour, owner_tz):
    """The job spec for one subscription topic: nightly at the delivery hour."""
    hour, minute = _hour_minute(delivery_hour)
    return {
        "name": f"pt-subscription-{topic['id']}",
        "schedule": f"{minute} {hour} * * *",
        "tz": owner_tz,
        "prompt": TOPIC_PROMPT.format(tid=topic["id"], depth="deep"),
    }


def oneoff_job(topic):
    """A pending one-off's own edition, one-shot at its scheduled_for."""
    return {
        "name": f"pt-oneoff-{topic['id']}",
        "schedule": topic["scheduled_for"],
        "tz": None,
        "prompt": TOPIC_PROMPT.format(tid=topic["id"], depth=topic["depth"]),
    }


def desired_jobs(topics, delivery_hour, owner_tz,
                 lead_minutes=DEFAULT_LEAD_MINUTES, extra_hours=()):
    """The jobs the topic store calls for, in spec order.

    The daily edition comes first (it is the main paper), then one job per
    extra delivery time (delivery.extra_hours -- the same MAIN roster,
    re-researched later the same day), then one job per distinct section
    deliver_at that is not delivery.hour (a different newspaper), then one
    job per subscription, then one per pending one-off at its scheduled_for
    still ahead (topics.py refuses one without an offset; a past one is
    not re-armed). Hours are the owner's and register in the owner's zone;
    lead_minutes is the nominal lead, clamped per slot (see _lead).
    """
    focused_hours = focused_paper_hours(topics, delivery_hour)
    require_workspace_spacing([delivery_hour, *extra_hours, *focused_hours])
    jobs = []
    # The daily paper always exists once setup can register: weather and
    # calendar run even with zero news sections.
    jobs.append(daily_job(delivery_hour, _lead(delivery_hour, lead_minutes), owner_tz))
    for n, hour in enumerate(extra_hours, start=2):
        jobs.append(daily_job(hour, _lead(hour, lead_minutes), owner_tz, name=f"{DAILY_NAME}-{n}"))
    for hour in focused_hours:
        jobs.append(paper_job(hour, _lead(hour, lead_minutes), owner_tz))
    jobs.extend(
        subscription_job(t, delivery_hour, owner_tz)
        for t in topics
        if t["kind"] == "subscription" and t["status"] != "cancelled"
    )
    now = datetime.now().astimezone()
    jobs.extend(
        oneoff_job(t)
        for t in topics
        if t["kind"] == "one_off" and t["status"] == "pending" and t.get("scheduled_for")
        and datetime.fromisoformat(t["scheduled_for"]).astimezone() > now
    )
    return jobs


def stale_names(topics, registered, extra_hours_count=0, delivery_hour=None):
    """Registered pt-* jobs the topic store no longer calls for.

    A subscription job outlives only its non-cancelled topic; a one-off job
    outlives only a topic still pending or running (a fired one-shot stays
    registered as completed; this sweep prunes it once the topic is
    delivered, cancelled or gone). The daily job is never stale; a
    numbered extra-daily job goes stale the moment the owner removes that
    many delivery times. A pt-paper-HHMM job outlives only an active section still at that
    hour (and not the main delivery.hour). Names not starting with pt- are
    never ours to remove.
    """
    by_id = {t["id"]: t for t in topics}
    live_papers = set()
    if delivery_hour is not None:
        live_papers = {paper_job_name(h) for h in focused_paper_hours(topics, delivery_hour)}
    stale = []
    for name in registered:
        if name == DAILY_NAME:
            continue
        extra_match = _EXTRA_DAILY_RE.fullmatch(name)
        if extra_match is not None:
            n = int(extra_match.group("n"))
            if n > extra_hours_count + 1:
                stale.append(name)
            continue
        if _PAPER_RE.fullmatch(name):
            if delivery_hour is not None and name not in live_papers:
                stale.append(name)
            continue
        match = _JOB_NAME_RE.fullmatch(name)
        if match is None:
            continue
        kind, tid = match.group("kind"), match.group("tid")
        topic = by_id.get(tid)
        if topic is None:
            stale.append(name)
        elif kind == "subscription" and topic["status"] == "cancelled":
            stale.append(name)
        elif kind == "oneoff" and topic["status"] in ("delivered", "cancelled"):
            stale.append(name)
    return stale


def registered_jobs(listing):
    """{name: job} for the pt-* jobs this spec manages, from a full listing.

    A managed name registered twice is refused rather than guessed at --
    editing or sweeping one of two copies leaves the other firing. The
    on-demand copy (pt-daily-edition-now) is the exception: queue_now
    replaces it by id.
    """
    registered = {}
    for job in listing:
        if not job.name.startswith("pt-") or job.name == NOW_NAME:
            continue
        if job.name in registered:
            raise SystemExit(
                f"refusing to register: {job.name} is registered twice "
                f"({registered[job.name].id}, {job.id}). Remove one with "
                f"`{' '.join(OPENCLAW)} cron rm <id>` and re-run.")
        registered[job.name] = job
    return registered


def _same_schedule(want, have, cron):
    if cron:
        return want == have
    try:  # one-shots come back normalized to UTC; compare the instant
        return datetime.fromisoformat(want).timestamp() == datetime.fromisoformat(
            have.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, AttributeError):
        return want == have


def job_drift(job, spec):
    """True when a registered job's reported fields contradict the spec.

    Only a field that is BOTH reported and different is a drift; an absent
    field is silence, not a mismatch. Schedule, zone, prompt and model are
    the fields a spec change actually moves (the delivery hour, the owner's
    zone, the lead, the delivery contract, the model the paper is tuned on).
    """
    for key in ("schedule", "tz", "prompt", "model"):
        have = spec.get(key)
        want = job.get(key, MODEL) if key == "model" else job.get(key)
        if have is None or want is None:
            continue
        if key == "schedule":
            if not _same_schedule(want, have, cron=job.get("tz") is not None):
                return True
        elif have != want:
            return True
    return False


def queue_now(backend, listing, lead_minutes, owner_tz, clock=None):
    """The on-demand copy: the main paper's own prompt as a one-shot job.

    The scheduler fires it exactly like the morning run -- its own session,
    the same workspace lock, the same delivery leg -- so "send me the paper
    now" can never be a thinner or different paper. Previous copies are
    removed by id only after the new one is created, so a failed create
    never cancels a copy the owner was already promised.
    """
    at = (clock or datetime.now(ZoneInfo(owner_tz))) + timedelta(minutes=1)
    job = {
        "name": NOW_NAME,
        "schedule": at.isoformat(timespec="seconds"),
        "tz": None,
        "prompt": paper_prompt(lead_minutes=lead_minutes),
    }
    previous = [j.id for j in listing if j.name == NOW_NAME]
    _check(backend.create(job), f"could not queue {NOW_NAME}")
    print(f"queued: {NOW_NAME} ({job['schedule']})")
    for job_id in previous:
        _check(backend.remove(job_id), f"could not remove the previous {NOW_NAME}")


def _check(proc, failure):
    if proc.returncode != 0:
        raise SystemExit(f"{failure}:\n{proc.stdout}\n{proc.stderr}")


def main(argv=None, backend=None, config_path=CONFIG_FILE, env=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # parse_args(None) on the CLI is sys.argv[1:], but in-process callers
    # pass [] so argparse never reads the test runner's argv.
    parser.add_argument(
        "--now", action="store_true",
        help="after registering, queue the main paper as a one-shot a minute "
             "out -- the on-demand copy, same prompt, no send clock",
    )
    args = parser.parse_args(argv if argv is not None else [])
    env = os.environ if env is None else env

    if backend is None:
        if not os.path.exists(OPENCLAW[1]):
            raise SystemExit(f"{OPENCLAW[1]} not found -- run this inside the agent container")
        backend = CronBackend()

    owner_tz = load_owner_zone(config_path)
    # The topic store, via pt-intake's single reader -- so a broken
    # topics.json refuses here too, rather than reading as "no topics" and
    # pruning every subscription job this run could have kept.
    import topics as topics_mod
    topics = topics_mod.load_topics()
    adopt_owner_clock(owner_tz, (env.get("TZ") or "").strip() or owner_tz, config_path)
    delivery_hour = load_delivery_hour(config_path)
    extra_hours = load_extra_hours(config_path)
    lead_minutes = load_lead_minutes(config_path)

    listing = backend.list()
    registered = registered_jobs(listing)
    paused = []
    pending = []

    for job in desired_jobs(topics, delivery_hour, owner_tz, lead_minutes, extra_hours):
        current = registered.get(job["name"])
        if current is not None:
            if not current.enabled:
                print(
                    f"WARNING: {job['name']} is registered but DISABLED -- it will "
                    "never fire, and this leaves it alone rather than "
                    f"duplicating it. Enable it: {' '.join(OPENCLAW)} cron enable {current.id}"
                )
                paused.append(job["name"])
                continue
            if not job_drift(job, current.spec):
                print(f"already present, skipped: {job['name']}")
                continue
            pending.append(("edit", job, current))
        else:
            pending.append(("create", job, None))

    for action, job, current in pending:
        if action == "edit":
            print(
                f"updating drifted job: {job['name']} "
                f"(was {current.spec.get('schedule')!r} {current.spec.get('tz')!r}, "
                f"now {job['schedule']!r} {job['tz']!r})"
            )
            _check(backend.edit(current.id, job), f"could not update drifted job {job['name']}")
            print(f"updated: {job['name']} ({job['schedule']})")
        else:
            _check(backend.create(job), f"could not register {job['name']}")
            print(f"registered: {job['name']} ({job['schedule']})")

    for name in stale_names(topics, registered, len(extra_hours), delivery_hour):
        _check(backend.remove(registered[name].id), f"could not remove stale job {name}")
        print(f"removed stale job: {name}")

    if args.now:
        queue_now(backend, listing, lead_minutes, owner_tz)

    if paused:
        raise SystemExit(
            f"registered what was missing, but {len(paused)} job(s) are "
            f"DISABLED and will never fire: {', '.join(paused)} -- "
            f"{' '.join(OPENCLAW)} cron enable <id>"
        )
    return 0


if __name__ == "__main__":
    # sys.argv[1:] explicitly: main(argv=None) parses [] on purpose, so the
    # CLI has to hand its arguments over itself, or no flag can ever be
    # passed from a terminal.
    sys.exit(main(sys.argv[1:]))
