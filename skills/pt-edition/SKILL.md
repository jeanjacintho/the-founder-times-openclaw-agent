---
name: pt-edition
description: Compile one or more topics' research notes into edition.json, render the Letter PDF plus any chat-only desk companion, and post them via post_to_chat.py, which finalizes carried topics and prints when configured. Runs in the cron-fired session after pt-research.
---

# pt-edition — notes become the edition

The edition is the product. Every rule here serves one idea: a reader on a
phone (or holding a printed page) gets a short, sourced answer, and nothing
in it is a guess.

## Write `edition.json`, never the layout

You compile structured content; the layout is code, not text. **Never write
HTML.** Hand-write `edition.json` under the run directory:

```json
{
  "date": "2026-09-11",
  "location": "Sao Paulo",
  "sections": [
    { "kind": "section", "desk": "weather",
      "title": "Weather",
      "headline": "Rain in the afternoon",
      "body": "3–6 sentences from desk-weather notes, city named.",
      "forecast": [
        { "day": "Tue", "date": "17/05", "icon": "partly-cloudy", "high": 19, "low": 9 }
      ],
      "sources": ["https://…"],
      "could_not_source": [] },
    { "kind": "section", "desk": "calendar",
      "title": "Calendar",
      "headline": "Two meetings before noon",
      "body": "9am — Product sync.\n\n11am — Investor call.\n\nUpcoming: Thu — dentist at 3pm.",
      "schedule": [
        { "time": "9am", "title": "Product sync", "icon": "meeting" },
        { "time": "11am", "title": "Investor call", "icon": "call" },
        { "time": "Thu", "title": "Dentist at 3pm", "icon": "reminder" }
      ],
      "sources": ["Calendar.app"] },
    { "kind": "section", "desk": "mail",
      "title": "Letters",
      "headline": "Three messages overnight",
      "body": "Ana Costa — partnership proposal.\n\nBanco XP — invoice available.\n\nGitHub — new pull request awaiting review.",
      "messages": [
        { "sender": "Ana Costa", "subject": "Partnership proposal" },
        { "sender": "Banco XP", "subject": "Invoice available" },
        { "sender": "GitHub", "subject": "New pull request awaiting review" }
      ],
      "sources": ["Gmail"] },
    { "kind": "section", "desk": "sports",
      "title": "Sports",
      "headline": "Flamengo takes the field tonight",
      "body": "Flamengo hosts Palmeiras tonight at 9pm for the Brasileirão. Corinthians lead São Paulo 1–0 in the second half. Grêmio and Internacional drew 2–2 in today's early game.",
      "games": [
        { "home": "Flamengo", "away": "Palmeiras", "status": "scheduled", "note": "Tonight, 9pm" },
        { "home": "Corinthians", "away": "São Paulo", "status": "live", "home_score": 1, "away_score": 0, "note": "62'" },
        { "home": "Grêmio", "away": "Internacional", "status": "final", "home_score": 2, "away_score": 2 }
      ],
      "sources": ["https://site.api.espn.com"] },
    { "kind": "section", "topic_id": "t_8c1d", "desk": "news",
      "title": "The dollar",
      "headline": "The real headline",
      "body": "3–6 sentences, every one traceable to a note.",
      "sources": ["https://…"],
      "could_not_source": ["…"] },
    { "kind": "assignment", "topic_id": "t_3f2a", "run_on": "2026-09-11",
      "desk": "news",
      "title": "iPhone 15 price",
      "body": "…", "sources": ["https://…"],
      "tag": "special for this edition",
      "could_not_source": ["…"] }
  ]
}
```

- **`topic_id` is mandatory per section** — `post_to_chat.py` finalizes
  each topic from it. `run_on` is required for an assignment.
- **The title is the topic's text**, trimmed of pleasantries; it is the
  owner's own words.
- **Write `headline` and `body` in `pt/config.json`'s `owner.language`**
  (SOUL.md's language rule): research the sources in whatever language
  they're in, then write the synthesis in the owner's. `title` stays
  exactly as the owner phrased their topic, even in another language —
  never retranslate someone's own words. No `owner.language` at all is the
  one case to fall back on the language the sourced notes themselves read
  most naturally in, never a hardcoded default.
- **3–6 sentences per body, every one traceable to a note.** If a claim is
  not backed by a note, cut the sentence.
- **`could_not_source` is per section, not global** — it belongs to the block
  it qualifies. Unsourced claims are named, not hidden.
- **Every desk prints `could_not_source`, and every desk but priority
  prints `sources`**, in the reader's words ("your calendar", never a file
  or a path). Priority sources were the paper's own plumbing ("Sources:
  priority desk"), so the renderer drops them there. Weather on the
  printed page is the masthead ear (a vendored Atlas icon and high/low, or
  the named miss when research failed); it has no sources line. The chat
  edition still prints weather sources and gaps.
- **`desk` is the newspaper department.** At the front of the printed paper,
  weather occupies the masthead ear, priority occupies the founder-focus
  band, calendar occupies the sole right rail, and news occupies the main
  well. The longest news body leads at full width; article order breaks ties
  and otherwise preserves the pair below it. Mail and sports remain in the
  chat edition but do not consume print space. Every desk keeps the same title / headline /
  body / sources shape; the priority desk carries `sources: []`.
- **`priority` is optional, priority-desk-only, and copied from
  `run/desk-priority/tournament.json` without rewriting.** The printed card
  already talks to the reader. When present it replaces the section prose on print. Shape:
  `recommendations` is exactly three ranked objects, each with non-blank `headline`, `body`,
  `first_step`, `evidence` (one to three `{claim, source, url?}` items), and
  `advisor: {name, quote, url}`; `body` is at most 1,024 characters and every present `url`
  is HTTP(S). `questions` is zero to three non-blank strings. The advisor desk owns all semantic
  judgment; the renderer enforces only shape, length, URL form, escaping, and layout.
- **`forecast` is optional, weather-only, and drawn — not written.** Exactly
  one day object: `day` (short label, e.g. "Tue"), `date` (e.g.
  "17/05"), `icon` (exactly one of `sun`, `partly-cloudy`, `cloud`,
  `rain`, `storm`, `snow` — the renderer draws a vendored monochrome icon
  for each key, so anything else fails the gate), and `high`/`low`
  (numbers, the units come from the template, not the JSON) — deliberately
  temperatures and the icon only, nothing else; wind/humidity/precip
  the ear stays readable at a glance. That one day is `{{WEATHER_EAR}}`.
  Extra days are not in the schema and do not reach chat. Leave `forecast`
  out only when today's icon + high/low could not be sourced, and let
  the prose `body` plus `could_not_source` carry the weather in chat.
- **`schedule` (calendar-only), `messages` (mail-only) and `games`
  (sports-only) are the same idea as `forecast`, optional and drawn.**
  `schedule` is a non-empty list of `{ "time", "title", "icon" }`,
  `icon` exactly one of `meeting`, `call`, `task`, `reminder`, `note` —
  pick the one that actually matches the event (a call is `call`, not
  `meeting`; a standing reminder like "dentist at 3pm" is `reminder`;
  anything that doesn't fit the other four is `note`, never guessed as
  `meeting` to avoid picking). The printed calendar rail shows at most six
  events; list every event in `schedule` anyway — that list
  is the calendar source of truth, and the chat edition serializes it
  in full. Extra rows are dropped only in print. `messages` is a non-empty list of
  `{ "sender", "subject" }` — no icon field, since every letter draws
  the same envelope mark. `games` is a non-empty list of `{ "home",
  "away", "status", "home_score", "away_score", "note" }` — `status`
  exactly one of `scheduled`, `live`, `final`; `home_score`/`away_score`
  are required (integers) for `live`/`final` and meaningless for
  `scheduled`; `note` is optional free text (a kickoff time for
  `scheduled`, a clock/round for `live`, e.g. "62'", nothing needed for
  `final`). Mail and sports still need the prose `body` filled in (the
  chat edition has no icons to fall back on). A calendar desk with
  `schedule` can leave `body` as a short headline; include the
  structured field only when the notes actually give you distinct
  events, senders or games to list, not as a mandatory duplicate of the
  prose.
- **`image` (news sections only) is optional: `{ "url", "credit" }`** —
  only an image pt-research captured under its reuse rule. `url` is the
  direct link to the image file itself, `credit` a short optional line
  ("Reuters", "AP Photo/Jane Doe") printed under the photo.
  render_edition.py fetches, grayscales and crops it; a bad URL, a timeout
  or a non-image response just means the story prints without a photo.
  When in doubt, leave `image` out.
- **Calendar and mail bodies are one item per paragraph, blank-line
  separated — never joined with periods into one run-on sentence.** The
  template renders each paragraph as its own bulleted line; "9am —
  Product sync.\n\n11am — Investor call." reads as two clean bullets,
  "9am — Product sync. 11am — Investor call." reads as a dense wall of
  text. One event, one sender, one line each.
- The daily paper always includes weather and calendar from
  `run/desk-*/notes.json`. If calendar notes list `could_not_source` and
  no events, the headline says the paper could not read the agenda (never
  a free day — desks.md §2). **Priority is the same when `pt/config.json` has
  `priority.configured: true`: always a `"desk": "priority"` section.** Copy
  its `priority` object from `run/desk-priority/tournament.json` without rewriting. An
  on-demand copy reusing an older checkpoint also sets the section's `"as_of"` to that
  checkpoint's `date`; the card then prints "Advice from <date>". If that
  complete checkpoint is missing, or the **As of** date in
  `pt/advisor.md` is not today (on demand: not the reused checkpoint's `as_of`), write the
  unavailable section instead: a one-line `body` saying today's card could not be built, and
  `could_not_source` copied verbatim from `run/desk-priority/notes.json` when its `date` is
  this edition's (that desk is kept across days; an older file's reason is not today's).
  `render_edition.py` refuses a configured paper with no priority section, and an
  unavailable one with no reason. Never omit the slot. Mail only when
  `pt/config.json` has
  `mail.configured: true` **and** `run/desk-mail/notes.json` exists;
  otherwise omit the mail block entirely so that slot stays empty.
  Sports is the same pattern: only when `pt/config.json` has
  `sports.configured: true` **and** `run/desk-sports/notes.json`
  exists; otherwise omit the sports block entirely — never fill it with
  a generic league digest just because a desk slot exists for it. Compile
  **only** the news topics this run researched (pt-research decides which
  belong to this paper's hour). Owner
  `section` and `assignment` topics are always `"desk": "news"`. Do not put
  a news topic on the weather desk to make it look important.
- **Include no more than three news articles, and never hand-split copy.**
  Pagination is the renderer's job: it keeps every included word, news
  that does not fit one Letter sheet continues on page 2+ (WeasyPrint,
  `column-fill: auto`), each boxed desk stays whole, and the priority card
  may continue onto page 2. It never truncates or silently drops a fourth
  article.
- **A desk's notes file must be dated for today's edition.** A desk that
  fails to gather leaves the previous day's `run/desk-*/notes.json` /
  `events.json` in place. `render_edition.py` refuses an edition that carries a standing desk when any
  such file's `date` is missing or not the edition's `date`; re-run that
  desk, or delete its stale files. `desk-priority` is kept across days and exempt;
  `--tournament` dates its card instead, and an unavailable card needs today's `notes.json`. A news-only edition (a one-topic
  subscription) renders no standing desk, so leftover desk files are not
  checked and need no action. Weather, calendar, and a configured priority
  desk are mandatory: after deleting, compile an honest failed-gather (priority:
  unavailable) section from the current reason, never drop them. Only mail
  and sports may be dropped as a logged miss. While the edition still carries a standing desk, the check reads
  all the files, so dropping one desk's section without deleting its files
  still refuses.
- **`location` is this run's city** from the Latch location step, a string,
  optional. It is the dateline, not a stored profile: if location failed,
  omit the field.
- **Never pad** (SOUL.md). An empty pass (zero sourced claims) is still an edition: the title, one honest
  sentence ("nothing to report this time"), and what was tried.
  A thin weather or calendar desk is still printed; it is a department of
  the paper, not optional filler.

## On demand — "send me the paper now"

Not a topic and not built in the chat turn: `pt-intake` queues the main
paper's own prompt as a one-shot with
`/opt/plow/skills/pt-dashboard/scripts/register_crons.py --now`, and
this skill delivers it from that session like any other paper (no
`--hold-until`; the advisor card per desks.md, dated with `as_of` when older).

## Render and deliver

1. Run the renderer — it is the only thing that writes the edition. One
   complete command, printer or not; **copy it and change only the
   paths.** Do not add flags that are not here:

       /opt/plow/skills/pt-edition/scripts/render_edition.py <edition.json> --tournament /var/lib/plow/pt/run/desk-priority/tournament.json --pdf run/<id>/edition.pdf --companion run/<id>/edition.companion.txt

   The printed page is this same PDF. `--chat PATH` is optional and takes
   a path when used; the chat transcript is not posted, so you normally
   leave it out entirely.

   For an edition carrying `priority.recommendations`, `--tournament` is the delivery gate, not an
   optional decoration. It refuses fewer than three completed generations, an unfinished
   checkpoint, or a card that differs from the checkpoint. Topic-only editions and the honest
   unavailable-card fallback have no recommendations, so this flag does not require a tournament
   for them. Return to the priority tournament and run a missing generation; never edit its
   generation number merely to satisfy the gate.

   **Continue only when the renderer exits zero and
   `run/<id>/edition.pdf` exists.** The renderer removes an old target before
   trying, so a refusal can never leave yesterday's PDF looking successful.
   If it does not, read the renderer's own stderr and act on which failure
   it was:

   - **A usage error** (`exit_code: 2`, e.g. `argument --chat: expected one
     argument`) means YOUR command was wrong, not that the PDF is
     impossible. Fix the command and re-run it. This is **not** the
     weasyprint fallback and must never be treated as one.
   - **A malformed `edition.json`** is refused by name, and so is a page
     rule (below). Edit only the named field, never the rest of the copy,
     and re-run; never hand-assemble a page to route around the gate.
   - **Only** when the renderer's stderr says *weasyprint is not installed*
     is the PDF genuinely impossible — that costs the PDF file alone; take
     the text fallback in step 2 and do not write the edition by hand.

2. **Send the PDF yourself, by running `post_to_chat.py --pdf`, instead of
   returning the transcript as your final response.** If the renderer wrote
   `edition.companion.txt`, it contains only the mail/sports desks omitted
   from print; include it with `--text-file`. This is not the full chat dump:

       /opt/plow/skills/pt-shared/scripts/post_to_chat.py --pdf run/<id>/edition.pdf --text-file run/<id>/edition.companion.txt --filename The-Founder-Times-<date>.pdf

   When no companion file exists, omit only `--text-file`; the PDF posts with
   an empty body, the same envelope used for attachment-only sends.

   A **scheduled** paper's cron prompt adds `--hold-until HH:MM` (that job's
   delivery hour). Honor it: the script sleeps until that clock in `TZ`, and
   if the hour has already passed it posts immediately (never until tomorrow).
   The on-demand copy's prompt carries none.

   Omit `--pdf` **only** when step 1 established that weasyprint is
   genuinely absent — never because your own command failed. In that one
   case the text leg is also a complete command, with no shell redirect:

       /opt/plow/skills/pt-shared/scripts/post_to_chat.py --text-file run/<id>/edition.chat.txt

   Use `--text-file`, never `< file`, never `/bin/sh -c`, never a pipe
   (SOUL.md: one bare line). Pointing `--pdf` at a file that does not exist is
   refused by name.
   `PLOW_API_BASE`, `PLOW_HOME_CHANNEL` and `PLOW_AGENT_TOKEN` come from the
   process environment already; nothing to pass for those.

   After either POST, `post_to_chat.py` prints the run's PDF itself when
   `printer.configured` is true (the text leg too, so a missing PDF is
   reported), records the edition in the owner's wiki (`record_edition.py`
   on the sibling `edition.json`), and finalizes the carried topics. Do
   **not** call `pt-print` or `print_edition.py` after this. A print miss
   posts one `page not printed — …` line to chat by itself. A recorder
   failure exits non-zero after every finalizer and names the one recovery
   command, `record_edition.py <edition.json> --now <delivered_at>; do not
   repost` — `--now` is the moment captured right before the chat POST,
   under the delivery-order lock, so a retry still records the true
   delivery order rather than the moment you happen to run it. Run that
   command once, verbatim; never resend the PDF.
3. **Do not mark topics after posting.** On the successful POST boundary,
   `post_to_chat.py` atomically stamps only the `topic_id`s carried by its sibling
   `edition.json`: one-offs and assignments become `delivered`; sections and
   subscriptions record `last_edition_at` and become `pending`. Cancelled topics
   remain cancelled. Weather, calendar, mail and sports have no topic id.

## Repo note — the edition gate

The renderer validates `edition.json` structurally before emitting anything
(the same discipline `pt_config_gate.py` holds for the config): a bad shape
exits non-zero with the failing field named. Page rules then refuse the
priority card the same way: its own recommendation prose names no file or path and never labels
the reader in the third person ("the founder", "the CEO", "the owner", "o fundador" and the
like). Content ranking and quote selection belong to the advisor desk, not this deterministic
gate. Other desks get the structural gate only. A run that cannot render says so
and waits for the next cycle — it does not ship a half page.
