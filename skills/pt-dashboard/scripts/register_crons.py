#!/usr/bin/env python3
"""Register the Founder Times' crons, idempotently, from the topic store.

Why this exists at all. `hermes cron` persists jobs to
/var/lib/hermes/cron/jobs.json, which no rebuild replays -- so a rebuilt
agent would come up with subscriptions that never fire and nothing to diff
against. Keeping the spec here, derived from pt/topics.json (the one record
of what the owner asked to be watched), means "set up the plow times crons"
replays a reviewed derivation instead of improvising schedules from a
sentence. The same mechanism ld-dashboard's register_crons.py uses, with a
spec that is data-driven rather than fixed: the topic list changes.

The spec (design doc §3.6 and the personalized-paper plan §3.3/§6):

  pt-daily-edition       <min> <hour> * * *        one job; exists while
                         computed as                setup can register
                         delivery.hour -
                         lead_minutes (owner
                         zone, never before
                         midnight)
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

This script therefore CREATES missing jobs and REMOVES pt-* jobs whose
topic is gone -- cancelled, delivered one-offs, or names with no topic
behind them. "Created/removed as topics change", the design doc calls it. It never touches a job whose name does
not start with pt-: those are not this agent's to manage.

It also RECONCILES drift, which create-if-missing alone does not: a job
that is registered with a different schedule, skill or prompt than the spec
calls for (the owner changed delivery.hour, the lead changed, the delivery
contract moved -- PDF-only vs transcript) is updated in place with
`hermes cron edit`. Without this, "already present, skipped" means a
changed delivery hour or a new chat payload is silently ignored forever --
the exact class of failure this script exists to prevent. Drift is only
judged when hermes's own jobs.json carries the field; a fixture or an older
row without a schedule is left alone rather than edited on a guess. A
blank PLOW_HOME_CHANNEL (typical of docker compose exec, which does not
inherit s6's env) must refuse before any create or edit, while the
existing morning job is still registered. Never remove-then-create a
drifted job: if create failed after remove, the morning paper had no job
until someone reran the script.

One refusal is the point of the script, inherited from ld-dashboard: an
unreadable or unexpected jobs.json aborts. Never read "I could not tell what
is registered" as "nothing is" -- that re-registers every job and duplicates
all of them.

Every stored hour -- delivery.hour, extra_hours, a section's deliver_at --
is the owner's wall clock in owner.timezone. `hermes cron create` takes no
per-job zone and fires on the container's clock (TZ), as post_to_chat.py's
--hold-until waits on it, so this script converts each hour into TZ when it
registers, on today's date. A config still carrying delivery.local_hour was
written when delivery.hour was on the container's clock; adopt_owner_clock()
retires it on the next registration.

It runs INSIDE the container, where /opt/hermes/bin/hermes and that file
live -- from a turn, which inherits PLOW_HOME_CHANNEL from the gateway.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_SKILLS = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", "..")
sys.path[:0] = [os.path.join(_SKILLS, "pt-intake", "scripts"), os.path.join(_SKILLS, "pt-shared", "scripts")]
from record_owner_language import _write_json  # noqa: E402 -- the config's atomic writer
from pt_paths import config_file, script  # noqa: E402

HERMES = "/opt/hermes/bin/hermes"
# Where `hermes cron` persists its jobs -- nothing replays it on a rebuild,
# which is the reason this script exists.
JOBS_FILE = "/var/lib/hermes/cron/jobs.json"
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

# One topic's own edition: a subscription's nightly run or a one-off.
TOPIC_PROMPT = (
    "Run pt-research on topic {tid} now (depth {depth}), then pt-edition for it, "
    "delivering with post_to_chat.py per pt-edition/SKILL.md step 2. Final "
    "response is NO_REPLY so --deliver does not send the text a second time."
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
    Cron may start earlier via lead_minutes; POST must still wait. The
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
        "there is one, else run the tournament"
        if hold_until else
        "reuse the newest accepted checkpoint in run/desk-priority/tournament.json whatever "
        "its date -- an older one prints with \"as_of\" per pt-edition -- and run the "
        "tournament only if none has ever been accepted"
    )
    return (
        f"Run {title} now, in one session. First run {lock} acquire "
        f"--name {WORKSPACE_LOCK}-<today's date in the owner's "
        f"zone> --stale-minutes {STALE_RUN_MINUTES + lead_minutes}; if its output is 'held', "
        f"another paper owns the workspace -- say NO_REPLY and stop. Then "
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
        f"Release the lock with {lock} release --name the same {WORKSPACE_LOCK}-<date>. "
        f"Final response is NO_REPLY so --deliver does not send the transcript."
    )


DELIVER_TARGET = "plow_chat:${PLOW_HOME_CHANNEL}"


def load_zones(config_path=CONFIG_FILE, env=None):
    """(owner zone, container zone), or refuse.

    Refused: a container with no TZ (nothing here can name the clock cron
    fires on) and a config without owner.timezone.
    """
    env = os.environ if env is None else env
    container = (env.get("TZ") or "").strip()
    if not container:
        raise SystemExit(
            "refusing to register: TZ is empty in this container. Set TZ "
            "in compose.yml's environment (e.g. America/Sao_Paulo) and "
            "restart -- nothing else here fires without it, and the "
            "schedules would otherwise fire in a zone nothing here can name."
        )
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
    return owner, container


def adopt_owner_clock(owner_tz, container_tz, config_path=CONFIG_FILE):
    """Retire delivery.local_hour, left by setup when delivery.hour was stored
    on the container's clock. With one zone that hour already is the owner's;
    across two zones it is not recoverable without guessing through offsets.
    """
    path = pathlib.Path(config_path)
    config = json.loads(path.read_text())
    if "local_hour" not in config["delivery"]:
        return
    if owner_tz != container_tz:
        raise SystemExit(
            f"refusing to register: {path} predates owner-clock hours and its times "
            f"are on the container's clock ({container_tz}), not the owner's "
            f"({owner_tz}). Ask the owner for their delivery time, extra hours and "
            "paper times again, write them as their own clock, remove "
            "delivery.local_hour, and re-run.")
    del config["delivery"]["local_hour"]
    _write_json(path, config)


def _job_rows(jobs_path):
    """hermes's persisted job rows; only a missing file means none."""
    try:
        return json.loads(pathlib.Path(jobs_path).read_text())["jobs"]
    except FileNotFoundError:
        return []


def registered_jobs(jobs_path=JOBS_FILE):
    """What is already scheduled, from hermes's own persisted state.

    Reads the file `hermes cron` writes rather than parsing `hermes cron
    list` -- a human rendering nothing pins. Returns {name: is_runnable};
    a paused job is registered but will never fire, and the caller must
    tell those apart (re-registering duplicates it, skipping it silently
    strands it).

    The invariant with teeth: never read "I could not tell what is
    registered" as "nothing is". Only FileNotFoundError means empty -- an
    unreadable or unexpected file raises and stops the run.
    """
    jobs = _job_rows(jobs_path)
    return {
        job["name"]: bool(job["enabled"]) and not job["paused_at"]
        for job in jobs
    }


def resolve_deliver(deliver, env=None):
    """Expand every ${VAR} in a delivery target from the container environment.

    The chat uid is whichever chat the owner holds with this agent -- never
    a literal in this repo. First boot publishes PLOW_HOME_CHANNEL; run this
    from a turn, which inherits it from the gateway. Unset or blank REFUSES
    loudly: an empty target is a chat leg that silently delivers nowhere.
    """
    import re

    values = os.environ if env is None else env
    source = "the container environment" if env is None else "the injected env"

    def expand(match):
        name = match.group(1)
        value = (values.get(name) or "").strip()
        if not value:
            raise SystemExit(
                f"refusing to register: deliver target {deliver!r} needs {name}, "
                f"which is unset or blank in {source}. Registering without it "
                "would create a chat leg that silently delivers nowhere."
            )
        return value

    return re.sub(r"\$\{(\w+)\}", expand, deliver)


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


def _slot(hour, lead_minutes, owner_tz, container_tz):
    """(container HH:MM, lead) for one owner-clock hour.

    Cron and --hold-until run on the container's clock. The lead is clamped
    so the run never starts before midnight on either clock -- the run's
    lock and paper are dated in the owner's zone.
    """
    h, m = _hour_minute(hour)
    at = datetime.now(ZoneInfo(owner_tz)).replace(hour=h, minute=m, second=0, microsecond=0)
    at = at.astimezone(ZoneInfo(container_tz)).strftime("%H:%M")
    return at, min(lead_minutes, _minutes(hour), _minutes(at))


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


def daily_job(delivery_hour, lead_minutes, env=None, *, name=DAILY_NAME):
    """One full-paper delivery job -- the canonical slot, or an extra one."""
    return {
        "name": name,
        "schedule": daily_schedule(delivery_hour, lead_minutes),
        "prompt": paper_prompt(hold_until=delivery_hour, lead_minutes=lead_minutes),
        "skill": "pt-research",
        "deliver": DELIVER_TARGET,
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


def paper_job(hour, at, lead_minutes, env=None):
    """One focused paper: desks plus sections whose deliver_at is this hour.

    `at` is that hour on the container's clock."""
    name = paper_job_name(hour)
    return {
        "name": name,
        "schedule": daily_schedule(at, lead_minutes),
        "prompt": paper_prompt(hold_until=at, lead_minutes=lead_minutes, focus=hour),
        "skill": "pt-research",
        "deliver": DELIVER_TARGET,
    }


def subscription_job(topic, delivery_hour, env=None):
    """The job spec for one subscription topic: nightly at the delivery hour."""
    hour, minute = _hour_minute(delivery_hour)
    return {
        "name": f"pt-subscription-{topic['id']}",
        "schedule": f"{minute} {hour} * * *",
        "prompt": TOPIC_PROMPT.format(tid=topic["id"], depth="deep"),
        "skill": "pt-research",
        "deliver": DELIVER_TARGET,
    }


def oneoff_job(topic):
    """A pending one-off's own edition, one-shot at its scheduled_for."""
    return {
        "name": f"pt-oneoff-{topic['id']}",
        "schedule": topic["scheduled_for"],
        "prompt": TOPIC_PROMPT.format(tid=topic["id"], depth=topic["depth"]),
        "skill": "pt-research",
        "deliver": DELIVER_TARGET,
    }


def desired_jobs(topics, delivery_hour, owner_tz, container_tz, env=None,
                 lead_minutes=DEFAULT_LEAD_MINUTES, extra_hours=()):
    """The jobs the topic store calls for, in spec order.

    The daily edition comes first (it is the main paper), then one job per
    extra delivery time (delivery.extra_hours -- the same MAIN roster,
    re-researched later the same day), then one job per distinct section
    deliver_at that is not delivery.hour (a different newspaper), then one
    job per subscription, then one per pending one-off at its scheduled_for
    still ahead (topics.py refuses one without an offset; a past one is
    not re-armed). Hours are the owner's and register on the container's
    clock; lead_minutes is the nominal lead, clamped per slot (see _slot).
    """
    focused_hours = focused_paper_hours(topics, delivery_hour)
    require_workspace_spacing([delivery_hour, *extra_hours, *focused_hours])
    jobs = []

    def slot(hour):
        return _slot(hour, lead_minutes, owner_tz, container_tz)

    # The daily paper always exists once setup can register: weather and
    # calendar run even with zero news sections.
    main_at, main_lead = slot(delivery_hour)
    jobs.append(daily_job(main_at, main_lead, env))
    for n, hour in enumerate(extra_hours, start=2):
        jobs.append(daily_job(*slot(hour), env, name=f"{DAILY_NAME}-{n}"))
    for hour in focused_hours:
        at, lead = slot(hour)
        jobs.append(paper_job(hour, at, lead, env))
    jobs.extend(
        subscription_job(t, main_at, env)
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


def _persisted_schedule_expr(job):
    """The bare cron expression from a real job's persisted "schedule".

    Measured live against this fleet's own /var/lib/hermes/cron/jobs.json:
    a real registered job's "schedule" is a dict, {"kind": "cron", "expr":
    "15 2 * * *", "display": "15 2 * * *"} -- not the bare string this
    module's own job specs use. Comparing the dict to the spec's string
    directly (job_drift(), before this helper existed) made EVERY managed
    job register as "drifted" on every single run, recreating it every
    time register_crons.py ran -- caught live, not in the test suite, whose
    fixtures had always used a bare string and so never exercised the real
    shape.
    """
    schedule = job.get("schedule")
    if isinstance(schedule, dict):
        return schedule.get("expr")
    return schedule


def registered_specs(jobs_path=JOBS_FILE):
    """The registered jobs' own fields, for drift detection.

    registered_jobs() answers only "does it run"; this answers "does it match
    the spec". Only fields hermes actually persisted are returned -- a
    missing key means "unknown", and job_drift() leaves an unknown alone
    rather than recreating on a guess (older rows, and the test fixtures,
    carry no schedule).
    """
    jobs = _job_rows(jobs_path)
    return {
        job["name"]: {
            "schedule": _persisted_schedule_expr(job),
            "skill": job.get("skill"),
            "prompt": job.get("prompt"),
            "deliver": job.get("deliver"),
        }
        for job in jobs
    }


def job_drift(job, spec):
    """True when a registered job's persisted fields contradict the spec.

    Only a field that is BOTH persisted and different is a drift; an absent
    field is silence, not a mismatch. Schedule, skill and prompt are the
    fields a spec change actually moves (the delivery hour, the lead, the
    PDF-only vs transcript contract); deliver is not compared because its
    resolved form depends on the turn's environment and a false drift would
    edit every job on every run.
    """
    for key in ("schedule", "skill", "prompt"):
        stored = spec.get(key)
        if stored is not None and stored != job[key]:
            return True
    return False


def create_argv(job, env=None):
    argv = [HERMES, "cron", "create", job["schedule"], job["prompt"],
            "--name", job["name"], "--skill", job["skill"]]
    if job["deliver"]:
        argv += ["--deliver", resolve_deliver(job["deliver"], env)]
    return argv


def edit_argv(job, env=None):
    """Update a registered job in place. `hermes cron edit` takes the name
    (or id); never remove-then-create, or a failed create leaves no job."""
    argv = [HERMES, "cron", "edit", job["name"],
            "--schedule", job["schedule"],
            "--prompt", job["prompt"],
            "--skill", job["skill"]]
    if job["deliver"]:
        argv += ["--deliver", resolve_deliver(job["deliver"], env)]
    return argv


def queue_now(runner, jobs_path, lead_minutes, env=None, clock=None):
    """The on-demand copy: the main paper's own prompt as a one-shot job.

    The gateway's scheduler fires it exactly like the morning run -- its own
    session, the same workspace lock, the same --deliver -- so "send me the
    paper now" can never be a thinner or different paper. Names are not
    unique in hermes and a fired one-shot stays registered as completed, so
    previous rows are removed by id -- only after the new one is created, so
    a failed create never cancels a copy the owner was already promised.
    """
    at = (clock or datetime.now().astimezone()) + timedelta(minutes=1)
    job = {
        "name": NOW_NAME,
        "schedule": at.isoformat(timespec="seconds"),
        "prompt": paper_prompt(lead_minutes=lead_minutes),
        "skill": "pt-research",
        "deliver": DELIVER_TARGET,
    }
    previous = [j["id"] for j in _job_rows(jobs_path) if j["name"] == NOW_NAME]
    _check(runner(create_argv(job, env)), f"could not queue {NOW_NAME}")
    print(f"queued: {NOW_NAME} ({job['schedule']})")
    for job_id in previous:
        _check(runner([HERMES, "cron", "remove", job_id]), f"could not remove the previous {NOW_NAME}")


def _check(proc, failure):
    if proc.returncode != 0:
        raise SystemExit(f"{failure}:\n{proc.stdout}\n{proc.stderr}")


def _run(argv):
    return subprocess.run(argv, capture_output=True, text=True)


def main(argv=None, runner=_run, jobs_path=JOBS_FILE, config_path=CONFIG_FILE, env=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # parse_args(None) on the CLI is sys.argv[1:], but in-process callers
    # pass [] so argparse never reads the test runner's argv.
    parser.add_argument(
        "--now", action="store_true",
        help="after registering, queue the main paper as a one-shot a minute "
             "out -- the on-demand copy, same prompt, no send clock",
    )
    args = parser.parse_args(argv if argv is not None else [])

    if not shutil.which(HERMES) and not os.path.exists(HERMES):
        raise SystemExit(f"{HERMES} not found -- run this inside the agent container")

    owner_tz, container_tz = load_zones(config_path, env)
    # The topic store, via pt-intake's single reader -- so a broken
    # topics.json refuses here too, rather than reading as "no topics" and
    # pruning every subscription job this run could have kept.
    import topics as topics_mod
    topics = topics_mod.load_topics()
    adopt_owner_clock(owner_tz, container_tz, config_path)
    delivery_hour = load_delivery_hour(config_path)
    extra_hours = load_extra_hours(config_path)
    lead_minutes = load_lead_minutes(config_path)

    registered = registered_jobs(jobs_path)
    specs = registered_specs(jobs_path)
    paused = []
    pending = []

    for job in desired_jobs(topics, delivery_hour, owner_tz, container_tz, env,
                            lead_minutes, extra_hours):
        if job["name"] in registered:
            if not registered[job["name"]]:
                print(
                    f"WARNING: {job['name']} is registered but PAUSED -- it will "
                    "never fire, and this leaves it alone rather than "
                    f"duplicating it. Resume it: {HERMES} cron resume {job['name']}"
                )
                paused.append(job["name"])
                continue
            spec = specs.get(job["name"], {})
            if not job_drift(job, spec):
                print(f"already present, skipped: {job['name']}")
                continue
            pending.append(("edit", job, spec, edit_argv(job, env)))
        else:
            pending.append(("create", job, None, create_argv(job, env)))

    for action, job, spec, argv in pending:
        if action == "edit":
            print(
                f"updating drifted job: {job['name']} "
                f"(was {spec.get('schedule')!r}, now {job['schedule']!r})"
            )
        _check(runner(argv), f"could not {'update drifted job' if action == 'edit' else 'register'} "
                             f"{job['name']}")
        verb = "updated" if action == "edit" else "registered"
        print(f"{verb}: {job['name']} ({job['schedule']})")

    for name in stale_names(topics, registered, len(extra_hours), delivery_hour):
        _check(runner([HERMES, "cron", "remove", name]), f"could not remove stale job {name}")
        print(f"removed stale job: {name}")

    if args.now:
        queue_now(runner, jobs_path, lead_minutes, env)

    if paused:
        raise SystemExit(
            f"registered what was missing, but {len(paused)} job(s) are "
            f"PAUSED and will never fire: {', '.join(paused)} -- "
            f"{HERMES} cron resume <name>"
        )
    return 0


if __name__ == "__main__":
    # sys.argv[1:] explicitly: main(argv=None) parses [] on purpose, so the
    # CLI has to hand its arguments over itself, or no flag can ever be
    # passed from a terminal.
    sys.exit(main(sys.argv[1:]))
