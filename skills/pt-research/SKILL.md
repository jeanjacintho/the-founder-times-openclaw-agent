---
name: pt-research
description: One budget-bounded research pass — for a single topic, the main daily paper (standing desks plus unscoped news sections and assignments due today), or a focused paper at another hour (desks plus only the sections booked for that hour) — driving the owner's Mac through Latch (plow-gog for Gmail and Google Calendar, plow_run_applescript with pt-research/assets/calendar.applescript for Calendar.app, both per references/desks.md, plow_run_command for Mail.app fallback, plow_browser_* for every web page including weather and sports). Producing structured sourced notes. Runs in a cron-fired session. Stops at the budget, not when it feels done.
---

# pt-research — gather sourced notes within the budget

You are given one topic, or the daily paper's batch, and a depth budget. You
produce notes: for every claim, the source URL and a one-line quote or
paraphrase. You are not writing the edition here — pt-edition compiles these
notes into `edition.json` — so resist the pull toward polish. Claims, sources,
and honesty about what you could not find are the deliverable.

## The budget is the contract

| depth | sources | wall clock | browser calls (approx) |
|---|---|---|---|
| quick | 3–5 | ~5 minutes | ≤ 15 |
| deep | 8–12 | ~25 minutes | ≤ 60 |

**Stop at the budget, not when it feels done.** When the budget runs out,
you write down what you found and what you did not, and you stop. A pass
that found 3 of 5 sources reports 3 sources; it does not keep hunting.

## The loop

0. **Paper batch only — standing desks first.** Follow
   `pt-research/references/desks.md` before any news topic; it names every
   standing desk, when it runs, and in what order. Flush each desk's notes
   as you go. Do not skip a section because its status was delivered: the
   paper's prompt has already reopened yesterday's.
1. Read the topic (or each news topic of the batch) from `pt/topics.json` (the id
   is in your prompt). Mark it running first:
   `/opt/plow/skills/pt-intake/scripts/topics.py mark <id> --status running`. If it is
   already `running`, another run is working on it — skip it rather than
   racing it.

   Then, for a `section`, read what it already printed:
   `/opt/plow/skills/pt-priority/scripts/history.py recent --topic <id>`
   — `[{"date", "headline", "printed": [{"claim", "url"}]}]` for today and
   the 7 days before it, oldest first. Those URLs are already spent and
   those claims are already made: **this pass is what changed since the
   last date it lists**, not the subject again. Do not open a URL it names,
   and do not restate a claim it names, however well the search ranks it.
   An `error:` line is a failed read, not "none found": it loses the
   de-duplication, not the ability to research. Put that exact error in
   `could_not_source`, then research a fresh angle — the newest
   developments, not the subject's background — and open the body with one
   line, in the owner's language, saying earlier coverage could not be
   checked today, so a repeat is possible. Never research it as if its
   history were empty, and never leave the column blank for this alone;
   stop only when the batch budget is spent. An assignment
   has no history — it runs once, on its own day.

   When the window genuinely holds nothing newer, that is the answer: write
   the notes file short, name what you looked for in `could_not_source`, and
   let the edition say so. Refilling the column with the story it already
   ran is the failure this history exists to prevent.
2. Open the browser on the owner's Mac through Latch **once** (the rule
   below), with the origin starter list in `references/desks.md`. Then
   navigate.
3. For each page: extract the 2–4 facts it contributes, each with its URL and
   a one-line quote or tight paraphrase. Then move on. Do not re-read a page
   you have used; do not open a page that cannot add a new fact.
4. Write each topic's notes file as you go — not at the end — to
   `/var/lib/plow/pt/run/<topic_id>/notes.json`:

   ```json
   {
     "topic_id": "t_9f2a",
     "depth": "deep",
     "notes": [
       { "claim": "MCP tool search shipped Sep 4",
         "url": "https://example.com/changelog",
         "quote": "Server-side tool search is now in public beta" }
     ],
     "could_not_source": [ "pricing change announced this week" ],
     "sources_blocked": [ { "url": "https://paywalled.example", "why": "CAPTCHA" } ]
   }
   ```

5. Leave each topic's status alone after that — `post_to_chat.py`
   finalizes it on delivery. (A run that dies mid-pass leaves it `running`
   on purpose: a silent return to `pending` would make a failed pass look
   like no pass at all.)

## The daily batch, and a focused paper

The **main** paper's run hands you several topics at once: every active
`section` with no `deliver_at` (or `deliver_at` equal to `delivery.hour`),
plus every `assignment` with `run_on` on or before today. A **focused
paper** (`pt-paper-HHMM`) is the same desks, then **only** active sections
whose `deliver_at` is that hour — never unscoped sections, never another
hour's sections, never assignments.

Two rules make a batch survivable in one session:

- **Sections are always `quick`; assignments default `quick` too.** A section
  runs every day, so depth there would multiply the run's wall clock by the
  section count. Only an assignment the owner explicitly asked to be
  "properly" done runs `deep`. Desks are not topics: notes at
  `run/desk-<name>/notes.json`, and never `topics.py mark` a desk.
- **The batch budget is global, and the per-topic budget is a slice of it.**
  Keep a running total: when the batch budget is spent, stop starting new
  topics and write down what each one got. The edition ships with what was
  found — a section that got nothing says so — it never runs over to finish.
  Desks take a thin slice (local Latch reads plus one weather search; the
  advisor's passes keep pt-priority's own clock), then news sections share the rest.

Notes go to each topic's own `run/<topic_id>/notes.json`, flushed as you go,
so a session that dies halfway keeps every topic it finished. Desk notes
flush the same way.

## Rules that are not negotiable

- **Read-only.** No "accept cookies" beyond what navigation itself forces.
  If a source requires an account, it is a source you could not use.
- **A blocked source is a source you couldn't use — web page or tool call.**
  CAPTCHA, paywall, 403 on a page; an authorization error (401, 412, "could
  not authorise") from any connector a section reads through (a Google
  account, a mail connector, anything besides `plow_browser_*`): try it once,
  log it in `sources_blocked` / `could_not_source` with the exact error, spend
  no further calls on it, move on. Never retry the same blocked source more
  than once in a run — a fixed connection needs the owner to fix it.
- **One browser session for the whole paper.** `plow_browser_open` once, with
  origins for location, weather, Google, sports, and news — each host as
  apex, `www.`, and `*.example.com` together (Latch treats `techcrunch.com`
  and `*.techcrunch.com` as different). Keep that session through
  desks and news. Do not close after location and reopen with a
  weather-only list — every other host then fails as "outside the approved
  origins".
- **Widen with origins, or skip the host.** `plow_browser_request` with no
  `origins` returns `needs origins and/or credential_items`. Never call it
  empty; never retry that error. If goto says "outside the approved origins",
  request **once** with `origins: ["example.com", "www.example.com",
  "*.example.com"]` for that host, then goto again. If Latch answers
  `Paused for ~Ns` (three failures tripped the MCP brake), stop that tool
  for this host, log `sources_blocked`, continue. Do not sit in the pause.
- **No fabrication under pressure.** A thin budget produces a short notes
  file, never invented facts. `could_not_source` exists so the edition can
  say honestly what remains unknown — using it is success, not failure.
- **A story's optional `image` (see pt-edition's SKILL.md) is the
  exception, not the rule.** Only capture one when the source page
  itself is clearly offering it for reuse — its own `og:image`/social-
  preview image, or an RSS item's enclosure/media:thumbnail — the same
  thumbnail a link-preview card or feed reader would already show,
  never a photo pulled some other way off a page, and never one from a
  paywalled or explicitly restricted source. No image found that way is
  the normal case; leave the field out.

## When you finish — close the browser

Once every desk and every topic in the batch has its notes written (or the
budget ran out), close the session you opened in step 2 with
`plow_browser_close`, on every exit path, including a budget cutoff or an
early return. The browser runs on the owner's own Mac: a tab left open is a
window sitting on their screen, and the next pass opens another on top of it.

Print one line per topic: how many sourced claims, how many unsourced, and
the notes path. The session continues to pt-edition with the notes paths;
each edition is what the owner sees, and the notes are only its evidence.
