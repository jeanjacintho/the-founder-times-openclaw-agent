---
name: pt-dashboard
description: The Founder Times' cron spec — one nightly job per active subscription plus the pruning of stale pt-* jobs — and the idempotent registration that replays them from the topic store. Use when asked to set up, re-register, inspect or repair the paper's crons, after rebuilding the agent's home, and after pt-intake adds or cancels a subscription.
---

# The Founder Times — the cron spec

Two shapes plus the paper, all derived from `/var/lib/plow/pt/topics.json`
at run time — unlike `ld-dashboard`'s fixed seven rows, this spec is the
topic list:

| job | schedule | notes |
|---|---|---|
| `pt-daily-edition` | `<min> <hour> * * *`, computed as `delivery.hour − delivery.lead_minutes` (default 0) in the owner's zone, never before that day's midnight | one job; the **main** paper: desks, sections with no `deliver_at` (or `deliver_at` equal to this hour), and assignments due today. Cron may start early; `post_to_chat.py --hold-until` is the send clock |
| `pt-daily-edition-<n>` (n ≥ 2) | same computation, against `delivery.extra_hours[n-2]` | reprint of that **same main** roster later the same day — not a different newspaper |
| `pt-paper-HHMM` | `<min> <hour> * * *` from a section `deliver_at` that is not `delivery.hour` (same lead subtraction) | one job per distinct hour; desks plus only the sections at that hour. Two sections at 12:30 share `pt-paper-1230`. A cancelled last section at that hour is pruned |
| `pt-subscription-<id>` | `<min> <hour> * * *` from `delivery.hour` | one per subscription topic not yet cancelled; created and removed as topics change |
| `pt-oneoff-<id>` | one-shot at the topic's `scheduled_for` (pt-intake: `now + 3m` quick, next `delivery.hour` deep) | one per pending one-off still ahead, so a rebuild re-creates it; a past one is not re-armed. The sweep removes it once the topic is delivered, cancelled or missing |
| `pt-deliver` | every minute | the outbox's flusher: a **no-agent command job** (`--command-argv` running `post_to_chat.py --flush-outbox` with the venv's python; no model, no tokens). Posts each staged paper once its hour has come. Every install has it; the sweep never removes it; it drifts only on its command |
| `pt-daily-edition-now` | one-shot, a minute out | `register_crons.py --now`: the main paper on demand, same prompt as `pt-daily-edition` without `--hold-until`; the next `--now` replaces it, the sweep never removes it |

The daily schedule is computed in minutes, so `00:00 − 0min` is `0 0 * * *`
(midnight itself). A lead that would reach back past midnight, such as
`00:00 − 20min`, is refused: that run would be the previous day's paper.

Every row is an agent turn in an **isolated** session, on
`plow/z-ai/glm-5.2` (the gateway's primary), with delivery **none**: the scheduler never
posts the run's final text anywhere. The edition itself is posted mid-run as
the PDF plus any chat-only mail/sports companion (`post_to_chat.py --pdf
--text-file`), to the owner's DM (`PLOW_HOME_CHANNEL`, or `owner_chat.py`
when boot did not know it yet). Every cron row carries `--tz` =
`owner.timezone`, so the scheduler fires on the owner's own wall clock,
daylight saving included; one-shots carry an ISO time with its offset.
Scheduled papers add `--hold-until` at that job's hour (read on the same
owner clock) so a recipe that finished early does not send before the clock;
the on-demand copy has none. Nothing waits in a session for that hour: the
paper is staged in `pt/outbox/` and `pt-deliver` posts it (a session sleeping
until the hour is killed by the exec timeout).

The daily run additionally takes a **run lock** with
`pt-shared/scripts/run_lock.py` (see the prompt this script writes): two runs
at once — a manual `openclaw cron run` beside the scheduled fire — would
otherwise see every section already `running`, compile an empty edition, and
deliver it. The lock is a file created with O_EXCL, so the two runs agree on
one owner.

## Registering

**This is a bring-up step, not a repair step.** The scheduler keeps its jobs
in `/var/lib/plow/state/openclaw.sqlite`, on the state volume: they survive a
gateway restart and `docker compose up --build` (the volume is kept), and are
**gone on a fresh volume** — an instance brought up that way has
subscriptions that never fire, and nothing to diff against, because the
failure looks identical to a producer running and finding nothing. Run it
after any new state volume, at the close of `pt-setup` (so the first
paper's job exists as soon as setup ends), and after pt-intake adds or
cancels a subscription, section or assignment.

    /opt/plow/skills/pt-dashboard/scripts/register_crons.py

**Then paste its output verbatim and report its exit status. The run is not
done until you have.** The script signals every refusal it has — a missing
or unusable config, a blank `owner.timezone`, an unreadable or truncated job
listing, a managed name registered twice, a failed `cron add`, `edit` or `rm`,
a registered-but-DISABLED job — through its output and a non-zero exit, and a
turn does not propagate an exit code. If you summarise instead of pasting,
"set up the crons, though one was paused" is an honest sentence describing a
run that failed, and nobody can tell. Do not paraphrase, and do not call it
done on a non-zero exit.

Create-if-missing, so it is safe to re-run: it reads what is already
scheduled from `openclaw cron list --all --json` (every job, disabled ones
included — a plain `cron list` hides them) and creates only what is absent.
It also **reconciles drift**: a registered job whose reported schedule,
zone, prompt or model no longer matches the spec — the owner changed the
delivery hour, the lead or their zone, the prompt's contract moved — is
patched in place with `openclaw cron edit <id>`, never removed and
re-created. Without that, "already present, skipped" would mean a changed
delivery hour is silently ignored forever. Drift is judged only against
fields the scheduler reported; an absent field is left alone, not edited on
a guess (one-shot times are compared as instants: the scheduler stores them
in UTC).
It removes `pt-daily-edition-<n>` whose number exceeds the current
`delivery.extra_hours` count, `pt-paper-HHMM` jobs whose hour no longer has
an active section, `pt-subscription-*` jobs whose
topic is cancelled, and `pt-oneoff-*` jobs whose topic is delivered,
cancelled or missing. The canonical `pt-daily-edition` stays registered
after setup — weather and calendar still need a run even with no news
topics. It never touches a job whose name is not one of
`pt-daily-edition`, `pt-daily-edition-<n>`, `pt-paper-*`, `pt-subscription-*` or
`pt-oneoff-*` with a real topic id behind it: those are not this spec's to
interpret or remove — **hand-registering a job by shell command instead of
writing the topic or `delivery.extra_hours` and re-running this script is
exactly the mistake this spec exists to make unnecessary**: such a job is
invisible to this sweep forever. OpenClaw's own jobs in the same list
(`heartbeat-main`, memory dreaming, skill review) are never touched. Registration never deletes runtime locks or
topic evidence; stale takeover belongs to `run_lock.py`, and evidence cleanup
belongs to the producer that knows when its consumers are finished.

Two refusals are the whole reason this is a script and not a habit:

- **An unreadable, partial or unexpected job listing aborts** — a failed
  `cron list`, non-JSON, a wrong shape, or `hasMore` (a truncated page).
  Never read "I could not tell what is registered" as "nothing is" — that
  re-registers every job and duplicates all of them. A managed name
  registered twice is refused too: editing or sweeping one of two copies
  leaves the other firing.
- **`owner.timezone` must be nameable.** Stored hours are the owner's clock
  and every job is registered in that zone. A config still carrying
  `delivery.local_hour` (an install from the previous runtime, whose hours
  were on its container clock) has that key dropped when that old `TZ` —
  if the environment still names it — equals `owner.timezone`; otherwise the
  script refuses and names how to re-state the owner's times.

A disabled job is neither skipped nor duplicated: it is left alone, named
with the command that enables it, and the run exits non-zero after
everything else finishes.

## Verifying an unattended run

From a turn (exec inherits the gateway token):

    node /app/openclaw.mjs cron list --all --json        # is the job there, and enabled?
    node /app/openclaw.mjs cron run <job-id> --json      # force one
    node /app/openclaw.mjs cron runs --id <job-id> --json  # then look for the edition in chat

A forced run exercises the whole path a nightly fire would take once it
starts; its `runId` starts with `manual:`. Only a scheduled fire proves the
schedule itself. A run recorded as `skipped` with a provider-preflight error
did not research anything: OpenClaw retries only at the job's **next**
scheduled time, so for the daily paper queue the day's copy with
`register_crons.py --now` once the provider answers again.

A subscription delivered unattended at least once is the MVP's own bar
of this migration: confirm the edition in the chat, not just that the cron
fired — a run that completes with no edition is the failure this whole
skill exists to surface.
