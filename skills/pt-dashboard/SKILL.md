---
name: pt-dashboard
description: The Founder Times' cron spec — one nightly job per active subscription plus the pruning of stale pt-* jobs — and the idempotent registration that replays them from the topic store. Use when asked to set up, re-register, inspect or repair the paper's crons, after rebuilding the agent's home, and after pt-intake adds or cancels a subscription.
---

# The Founder Times — the cron spec

Two shapes plus the paper, all derived from `/var/lib/hermes/pt/topics.json`
at run time — unlike `ld-dashboard`'s fixed seven rows, this spec is the
topic list:

| job | schedule | notes |
|---|---|---|
| `pt-daily-edition` | `<min> <hour> * * *`, computed as `delivery.hour − delivery.lead_minutes` (default 0) in the owner's zone, never before that day's midnight | one job; the **main** paper: desks, sections with no `deliver_at` (or `deliver_at` equal to this hour), and assignments due today. Cron may start early; `post_to_chat.py --hold-until` is the send clock |
| `pt-daily-edition-<n>` (n ≥ 2) | same computation, against `delivery.extra_hours[n-2]` | reprint of that **same main** roster later the same day — not a different newspaper |
| `pt-paper-HHMM` | `<min> <hour> * * *` from a section `deliver_at` that is not `delivery.hour` (same lead subtraction) | one job per distinct hour; desks plus only the sections at that hour. Two sections at 12:30 share `pt-paper-1230`. A cancelled last section at that hour is pruned |
| `pt-subscription-<id>` | `<min> <hour> * * *` from `delivery.hour` | one per subscription topic not yet cancelled; created and removed as topics change |
| `pt-oneoff-<id>` | one-shot at the topic's `scheduled_for` (pt-intake: `now + 3m` quick, next `delivery.hour` deep) | one per pending one-off still ahead, so a rebuild re-creates it; a past one is not re-armed. The sweep removes it once the topic is delivered, cancelled or missing |
| `pt-daily-edition-now` | one-shot, a minute out | `register_crons.py --now`: the main paper on demand, same prompt as `pt-daily-edition` without `--hold-until`; the next `--now` replaces it, the sweep never removes it |

The daily schedule is computed in minutes, so `00:00 − 0min` is `0 0 * * *`
(midnight itself). A lead that would reach back past midnight, such as
`00:00 − 20min`, is refused: that run would be the previous day's paper.

Every row still carries `--deliver plow_chat:${PLOW_HOME_CHANNEL}` (an
unset or blank `PLOW_HOME_CHANNEL` refuses the registration by name). The
edition itself is posted mid-run as the PDF plus any chat-only mail/sports
companion (`post_to_chat.py --pdf --text-file`). Scheduled papers add
`--hold-until` at that job's hour so a
recipe that finished early does not send before the clock; the on-demand
copy has none. The job's final response is `NO_REPLY` so that `--deliver`
does not also send the research transcript. An empty target is a chat
leg that silently delivers nowhere.

The daily run additionally takes a **run lock** with
`pt-shared/scripts/run_lock.py` (see the prompt this script writes): two runs
at once — a manual `hermes cron run` beside the scheduled fire — would
otherwise see every section already `running`, compile an empty edition, and
deliver it. The lock is a file created with O_EXCL, so the two runs agree on
one owner.

## Registering

**This is a bring-up step, not a repair step.** A rebuild does not replay
`jobs.json`, so an instance brought up without it has subscriptions that
never fire — and nothing to diff against, because the failure looks
identical to a producer running and finding nothing. Run it after `sign-in`,
after any rebuild of the home, at the close of `pt-setup` (so the first
paper's job exists as soon as setup ends), and after pt-intake adds or
cancels a subscription, section or assignment.

    /var/lib/hermes/skills/pt-dashboard/scripts/register_crons.py

**Then paste its output verbatim and report its exit status. The run is not
done until you have.** The script signals every refusal it has — a missing
or unusable config, a blank `owner.timezone`, an
empty `TZ`, a blank `PLOW_HOME_CHANNEL`, a failed `cron create`, `edit` or `remove`,
a registered-but-PAUSED job — through its output and a non-zero exit, and a
turn does not propagate an exit code. If you summarise instead of pasting,
"set up the crons, though one was paused" is an honest sentence describing a
run that failed, and nobody can tell. Do not paraphrase, and do not call it
done on a non-zero exit.

Create-if-missing, so it is safe to re-run: it reads what is already
scheduled from `/var/lib/hermes/cron/jobs.json` (the file `hermes cron`
itself writes — never the text of `hermes cron list`) and creates only what
is absent. It also **reconciles drift**: a registered job whose persisted
`schedule` or `skill` no longer matches the spec — the owner changed the
delivery hour or lead, the prompt's contract moved — is updated in place
with `hermes cron edit`. `--deliver` is expanded for every create and edit
**before** any hermes call, so a blank `PLOW_HOME_CHANNEL` refuses without
touching the morning job. Without that, "already present, skipped" would mean a
changed delivery hour is silently ignored forever. Drift is judged only against fields hermes
actually persisted; an absent field is left alone, not edited on a guess.
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
invisible to this sweep forever, and a hand-built one-off without
`--deliver` completes with nothing sent. Registration never deletes runtime locks or
topic evidence; stale takeover belongs to `run_lock.py`, and evidence cleanup
belongs to the producer that knows when its consumers are finished.

Two refusals are inherited from `ld-dashboard` and are the whole reason this
is a script and not a habit:

- **An unreadable or unexpected `jobs.json` aborts.** Never read "I could
  not tell what is registered" as "nothing is" — that re-registers every
  job and duplicates all of them.
- **The container's `TZ` and `owner.timezone` must both be nameable.**
  Stored hours are the owner's clock; `hermes cron create` takes no per-job
  zone, so the script converts each hour into `TZ` as it registers. A config
  still carrying `delivery.local_hour` (an older install) has that key
  dropped when `TZ` equals `owner.timezone`; otherwise the script refuses and
  names how to re-state the owner's times.

A paused job is neither skipped nor duplicated: it is left alone, named, and
the run exits non-zero after everything else finishes — the same contract
`ld-dashboard` holds.

## Verifying an unattended run

From inside the container:

    /opt/hermes/bin/hermes cron list          # is the job there, and not paused?
    /opt/hermes/bin/hermes cron run <job-id>  # force one
    /opt/hermes/bin/hermes cron runs          # then look for the edition in chat

A forced run exercises the whole path a nightly fire would take once it
starts. What it does not prove is that the running gateway loaded a
newly-created schedule — the `source=builtin` row in `cron runs` is the only
thing that proves that, and it takes a real scheduled fire.

A subscription delivered unattended at least once is the MVP's own bar
(docs/roadmap.md): confirm the edition in the chat, not just that the cron
fired — a run that completes with no edition is the failure this whole
skill exists to surface.
