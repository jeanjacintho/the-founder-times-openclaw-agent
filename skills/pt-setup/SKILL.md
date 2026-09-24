---
name: pt-setup
description: First-run interview over chat — settle the morning delivery hour, ask about a printer and probe it once through Latch, ask whether today's mail should join as a letters desk, then resolve the owner's timezone from Latch location. Use on the owner's first DM, including greetings (oi, oi de novo, hi, hello, hey), while pt/config.json is missing owner.timezone, delivery.hour or printer.configured. Never ask their timezone, name, or a personal profile. Never in a group, never in someone else's DM, and never to change one already-stored setting.
---

# pt-setup — the first conversation

This is a conversation, not a form. `/var/lib/plow/pt/config.json` and
`/var/lib/plow/pt/.setup-draft.json` are the **only** record of how far
it got — not the Plow Chat thread. Older messages about a printer or
letters after a wiped session are leftover; if the draft is missing,
start at the delivery hour. Do **not** ask their timezone — Latch location
at the end supplies `owner.timezone`. (`mail.configured` is asked in this
interview too, but a missing mail key is a valid older install — treat it
as false, do not restart setup for it.) Never re-ask something the draft
or config already holds.

**Every draft write, and every "what's next", goes through one script —
never a hand-edited `.setup-draft.json`, never your own judgement about
which question comes after which:**

    /opt/plow/skills/pt-shared/scripts/record_setup.py /var/lib/plow/pt/config.json key=value [key=value ...]

One line, no interpreter prefix, no shell operators — same rule SOUL.md
gives `setup_needed.py`. `key` is a dot-path (`local_hour`,
`printer.configured`, `printer.name`, `priority.configured`, `mail.configured`, `news_asked`,
`signals.group_chat`, `signals.email`, `signals.imessage`);
`true`/`false` become real JSON booleans, anything else stays a string. A
value with a space needs its own quoting, e.g. `printer.name="HP LaserJet 4"`.
It prints two lines:

    DRAFT:<fields already recorded>
    NEXT_QUESTION=<hour|printer|priority|mail|news|signals|close>

**Send exactly the one message `NEXT_QUESTION` calls for, then stop.**
Not that question plus the probe for the one after it. Not that question
plus a summary of what you just recorded. One question, one reply, then
wait for the owner. The questions below are written in two parts for
exactly this reason: part **a** is what you send and then stop for; part
**b** is what you do on their *next* message, before sending the
question after it.

**This interview never needs ad-hoc Python**, a heredoc, or any inline
script, for anything (SOUL.md): every action already has a named script
(`setup_needed.py`, `record_setup.py`, `pt_config_gate.py`) or a named tool
(`plow_run_command`, `plow_browser_*`). If you feel any pull to "just
check" something, re-read the current step instead.

Send the message the step calls for — **and only that message** —
in CHAT_VOICE (SOUL.md), answering what the owner actually said first.

**Slow work needs a hang-on, not a play-by-play.** Before any Latch call
or Mac file write, and again after every `plow_get_result` poll, run this
bare:

    /opt/plow/skills/pt-shared/scripts/chat_status.py --busy

It POSTs at most two ⏳ lines ("tô nessa", then "ainda nisso" if it is
still going). `STATUS:too-early` / `STATUS:already` is success; keep
working. Never type "checking the printer", "writing a file", a URL, or
a tool name.

**A greeting is this interview.** "oi", "oi de novo", "hi", "hello", "hey"
with a missing config is the opener below, not a hello-plus-help-menu and
not a continuation of a profile interview that already happened in this
chat.

**Opener — send this, then stop and wait.** Copy it. Match the owner's language.
Portuguese:

> 📰 Oi! Eu sou o The Founder Times (inspired by Mayfield), o seu jornal. A que horas você quer ele de manhã? Se não disser nada, mando às 7h.

English:

> 📰 Hi — I'm The Founder Times (inspired by Mayfield), your newspaper. What time should it land each morning? If you don't say, I'll send it at 7:00.

**Changing one setting later** is not this skill: a different delivery hour,
**a second (or third) daily delivery time** (`delivery.extra_hours`, a list
of "HH:MM" strings alongside `delivery.hour`, each in the owner's own
clock like `delivery.hour` itself — never ask the zone again), **turning the letters desk
on or off** (`mail.configured`), **turning a signal source on or off**
(see below), or a new printer is a
one-line conversation that updates `pt/config.json` directly. Before writing
a different `delivery.hour` (the owner's own HH:MM), run `topics.py check-paper
--deliver-at main --main-hour <HH:MM>`; if it refuses, name its
roster and leave the setting unchanged. After a valid change, re-run the gate
and then re-run
`/opt/plow/skills/pt-dashboard/scripts/register_crons.py` so the
new schedule exists now — not an interview from the top, and never a
hand-registered cron (see `pt-dashboard`).

**Turning a signal source on or off** after setup is one bare call,
never a hand-edited config:

    /opt/plow/skills/pt-shared/scripts/set_signal_source.py group_chat on
    /opt/plow/skills/pt-shared/scripts/set_signal_source.py email on
    /opt/plow/skills/pt-shared/scripts/set_signal_source.py imessage on

(`off` to stop). Before `email on` or `imessage on`, run the same probe as
5b and switch nothing on if it fails. It prints
`SIGNALS:group_chat=…,email=…,imessage=…`; confirm in one line. No cron
changes: the daily paper reads the switches itself.

## The questions, in order

Start of turn, every turn while `SETUP_NEEDED`: `setup_needed.py`'s second
line (`DRAFT:...`) or `record_setup.py`'s own `NEXT_QUESTION` from the
answer you just recorded says which of these you are on. Never infer it
from the draft's shape yourself, and never from what the chat thread
already discussed.

**1a. Ask the delivery hour, nothing else** — but only if the message
you are answering right now is a bare greeting ("oi", "hi", "hello")
with nothing else in it. **If it already reads like an hour answer
(see 1b's list), skip straight to 1b — do not send this question
again just because the draft still says `DRAFT:none`.** Otherwise: copy the locked hour line. Do not ask a
city, a zone, or a fuso — you will read that from Latch at the end. Send
only this, then stop.

Portuguese:

> 🕖 A que horas você quer o jornal de manhã? Se não disser nada, mando às 7h.

English:

> 🕖 What time should the morning paper land? If you don't say, I'll send it at 7:00.

**1b. On their next message**, treat any of "yes", "y", "sim", "ok",
"okay", "that", "default", "7", "7h", "7:00", "07:00", "pode", "isso", or
a skip as accepting 07:00; a clock time they name ("8:30", "08:30") is
that time. Record it and read the next question:

    record_setup.py /var/lib/plow/pt/config.json local_hour=07:00 owner.language=English

**Record `owner.language` in this same call**, as a plain-English name
("English", "Portuguese", "Mandarin Chinese"), read from what the owner
has actually written so far — not from this file's language, not from
their name, not from where they are. From here on the gate prints it back
as `LANG:` (SOUL.md).

Send only the `NEXT_QUESTION` it prints (question 2a), then stop. Do not
also probe the printer in this reply — that happens on their *next*
message, in 2b, never before question 2a has actually been sent to them.
Do not write `pt/config.json` yet: `owner.timezone` is still unknown, and
the gate would fail.

**2a. Ask whether a printer is set up on their Mac.** Copy the locked
line. Send only this, then stop — do not probe Latch yet.

Portuguese:

> 🖨️ Tem uma impressora no seu Mac? (sim / não)

English:

> 🖨️ Is there a printer on your Mac? (yes / no)

**2b. On their next message**, whatever they answered, **probe once
through Latch before recording `printer.configured`** — the same
discipline ld-setup applies to the Pi bring-up; a yes/no alone is a
configured printer that fails on every nightly run. First tool call of
this step is `chat_status.py --busy`. After every pending poll, `--busy`
again. Do not type a progress line.

Latch's `plow_run_command` schema requires **`argv`** and runs the array
directly — no shell, no `~`. Its optional keys (`goal`, `network`, `cwd`,
`read_paths`, `write_paths`, `apple_events`, `wait_ms`, …) are fine;
`additionalProperties: false` rejects anything else, so the relay errors
and the Mac never sees `lpstat`. OpenClaw names the tool
`plow__plow_run_command` (MCP server `plow`, then the Latch tool name). **Never send `"command"`.**

**This call needs `"network": true`.** `lpstat` reaches `cupsd` over a
local Unix domain socket, and Latch's sandbox grants socket access only
when `network` is true — the flag covers **local IPC**, not just remote
access. Without it libcups reports "Bad file descriptor" rather than a real
"no destinations" answer, every time.

Exact call:

```json
{
  "argv": ["lpstat", "-p"],
  "network": true,
  "goal": "List CUPS printers on the owner's Mac for newspaper setup"
}
```

If the result is `{"status":"pending","handle":…}`, poll
`plow_get_result` with that handle until `ready` (Latch's call budget is
10s, not a failed Mac). `denied` / `blocked` is the owner tapping No on
the Latch card, not an unreachable device.

**`network: true` is necessary but NOT sufficient.** `cupsd` is launched
on demand by launchd, and a *sandboxed* `lpstat` cannot trigger the launchd
rendezvous that starts it: with `cupsd` idle the sandboxed call returns
"Bad file descriptor" and leaves it asleep.

So if the call above comes back `exit_code` non-zero with an
error-shaped output (`"Bad file descriptor"`, or anything that is not a
destinations list or "No destinations added."), **retry once through
`plow_run_applescript`** — a different tool, which really does run
outside the sandbox:

```json
{"app": "System Events", "script": "do shell script \"lpstat -p\"", "goal": "Wake cupsd and list CUPS printers for newspaper setup (sandboxed probe failed)"}
```

Take its answer as the probe's answer. It also wakes `cupsd`, so later
sandboxed runs start working on their own.

**Do not** try this as `{"argv": ["osascript", "-e", "do shell script
…"]}` through `plow_run_command`: every argv handed to that tool runs under
the sandbox, `osascript` included, and reproduces the identical error. The
unsandboxed path is the `plow_run_applescript` *tool*.

A real "No destinations added." (or a genuine list) is a real answer.
Latch parked or unreachable is also an answer, not a reason to skip
2a — you already asked it; now record the probe's outcome:

- lpstat lists a printer:

      record_setup.py /var/lib/plow/pt/config.json printer.configured=true "printer.name=<exact CUPS name>"

  as a bare invocation, two space-separated arguments. Use exactly what
  `lpstat` printed, not the display name (macOS turns `.`/spaces into `_`
  in the queue name: "virtual-printer.online" in System Settings is
  `virtual_printer_online`). Only the *key* is split on dots, so the
  value is taken verbatim, whatever's in it; quote it only if it has a
  space. **Do not wrap this in** an interpreter or a heredoc (SOUL.md).
- lpstat's own output says there are none (e.g. "No destinations
  added."), Latch is parked, or the Mac is unreachable:

      record_setup.py /var/lib/plow/pt/config.json printer.configured=false

  and say, in the owner's own language, that the paper still delivers in chat; printing
  joins automatically if a printer shows up later (that is the
  changing-one-setting path, plus a re-probe).
- the call returned an error that isn't a real lpstat report — e.g.
  `exit_code` non-zero with output like "Bad file descriptor" rather
  than an actual destinations list or "No destinations added.": still

      record_setup.py /var/lib/plow/pt/config.json printer.configured=false

  (never guess `true` without a real listing), but say plainly, in
  their language, that the printer check itself didn't run cleanly —
  not "no printer was found." Those are different claims; only make
  the one that's actually true. Printing can still be turned on later
  once the check works.

Send only the `NEXT_QUESTION` it prints (question 3a), then stop.

## NEXT_QUESTION=priority

Copy the question (CHAT_VOICE), in the owner's language:

> ⭐ Every morning the paper can open with what Patrick Salyer would tell you after watching your last day. What are you trying to make true over the next few quarters? (or "no" to skip the advisor desk)

Stop. On their next message:

- **No** → `record_setup.py <config path> priority.configured=false`
- **An answer** → first put it in their wiki. Run `chat_status.py --busy` before the
  first Latch call and after each write; do not type that you are writing anything.
  1. `/opt/plow/skills/pt-shared/scripts/wiki_setup.py --desk` — it makes
     `~/Plow/wiki` ready (creating it when the Mac has none) and prints `WIKI:…`.
  2. `plow__plow_read_file` `path=~/Plow/wiki/entities/owner/goals.md`; add
     their answer as one `- ` line under `## Goals` unless it is already there, ending
     with its item — the shape intake's corrections use: a Messages chat plus rowid, or
     a named mail reader's message id, of the owner's own message; every setup answer
     arrives as one, so this is never optional. Set `updated:` to today. Read it again
     immediately before the write and fold whatever
     changed since the first read into what you write — the owner edits this page in
     Obsidian, and their line is evidence of what they say, never something a pass
     drops. Then `plow__plow_write_file` it back. Every other line, frontmatter
     included, stays as it was. Never paste the page back in chat.
  Only once the goal is on the page: `record_setup.py <config path> priority.configured=true`.
  No re-openable handle for that message (issue #85's non-phone-backed line) → same as
  No, no wiki write: the goal isn't supportable, so the desk stays unconfigured rather
  than stand on nothing — the paper still prints its other desks.
  An `error:` from step 1, or a denied or failed write → say so in one line and record
  nothing; the question stays open.
  Say in one line that the desk reads their Mac every morning, that they can correct it
  any time by texting ("Raj is my cousin", "stop telling me to hire"), and that their
  goals and the desk's Q&A are in their wiki at ~/Plow/wiki (it opens in Obsidian), where
  The Founder Times page shows how to add their own advisors.

Then continue with the mail question in the same turn.

**3a. Ask whether the paper should carry today's mail.** Copy the locked
line. Weather and calendar always run; mail is opt-in. Send only this, then stop.

Portuguese:

> ✉️ Quer as cartas do dia no jornal? Só quem mandou e o assunto, sem o texto todo. (sim / não)

English:

> ✉️ Want today's mail in the paper? Just who sent it and the subject, not the full text. (yes / no)

**3b. On their next message**, whatever they answered, **probe once
through Latch before recording `mail.configured`**, Google first,
Mail.app only if that fails. `--busy` before the probe and after every
poll; do not type what the probe is.

1. `plow_run_command` argv (exact):

```json
{ "argv": ["plow-gog", "gmail", "search", "newer_than:1d", "--max", "5", "--json", "--fields", "id,date,from,subject"] }
```

   A result (including zero messages) means the Google account in Latch
   works.
2. Only if that call is denied, 401/412, or Latch has no Google account:
   probe Mail.app:

```json
{ "argv": ["osascript", "-e", "tell application \"Mail\" to get name"], "apple_events": true, "goal": "See whether Mail.app is reachable for the letters desk" }
```

Then record the outcome:

- They said yes and **either** probe works:

      record_setup.py /var/lib/plow/pt/config.json mail.configured=true

- They said no, or both probes fail / the Mac is unreachable:

      record_setup.py /var/lib/plow/pt/config.json mail.configured=false

  and say, **in the owner's own language, the one they've been writing
  this chat in**, that the letters column can join later the same way a
  printer does. Never invent an inbox.

Send only the `NEXT_QUESTION` it prints (question 4a), then stop.

**4a. Ask what they want in the paper every day.** Copy the locked line.
Do not also add a "weather" news section unless they insist on a second,
different weather beat. "Nothing" / "skip" is a valid install. Send only
this, then stop.

Portuguese:

> 🗞️ O que você quer ver toda manhã? Pode ser futebol, tech, o dólar… ou “nada”, se o tempo e a agenda já bastarem.

English:

> 🗞️ What do you want to see every morning? Sports, tech, the dollar… or “nothing” if weather and your day already cover it.

**4b. On their next message** (including "nothing" / "skip"), take each
thing they name as a `section` topic via `pt-intake`'s writer
(`topics.py add --kind section --depth quick`), in the order they say
it — that order is the news desk's order. If they name more than three,
take the first three and say the cap; the daily run researches every news
section in one session and three is the paper's news-roster ceiling. Never invent a
section they did not ask for. Then, regardless of whether they named
any:

    record_setup.py /var/lib/plow/pt/config.json news_asked=true

Send only the `NEXT_QUESTION` it prints (question 5a), then stop.

**5a. Ask which signals the paper may listen to.** Copy the locked line.
Every source starts off; this is how the owner turns any of them on.
Send only this, then stop.

Portuguese:

> 👂 Quer que eu escute pra achar prioridades? Posso ouvir os grupos em que eu estiver (sem falar nada lá), seus e-mails e seus iMessages recebidos — filtrando spam e newsletter. Diga quais: grupos / e-mail / iMessage / nenhum.

English:

> 👂 Want me to listen for priorities? I can follow the group chats I'm in (without ever talking there), your incoming mail and your incoming iMessages — spam and newsletters filtered out. Say which: groups / mail / iMessage / none.

**5b. On their next message**, map what they named to three switches —
"nenhum" / "none" / "not now" is all three off. Before recording `true`:

- **email** needs Google reachable. If `mail.configured` is already
  `true`, 3b's probe proved it; otherwise run 3b's Google probe (same exact
  argv) and record `false` if it fails.
- **imessage** needs one probe through Latch — `chat_status.py --busy`
  first — with **exactly** the argv the daily scan uses, so the Mac's
  "always allow" covers the unattended runs:

```json
{ "argv": ["plow-messages", "search", "--limit", "200", "--order", "desc"], "read_paths": ["~/Library/Messages"], "goal": "Read incoming iMessages for the paper's priority signals" }
```

  A result (even zero rows) works; `blocked`, an error or an unreachable
  Mac records `false`.
- **group_chat** needs no probe.

Then, in one call:

    record_setup.py /var/lib/plow/pt/config.json signals.group_chat=<true|false> signals.email=<true|false> signals.imessage=<true|false>

If a source they asked for failed its probe, say in one line, in the
owner's language, that it can be switched on later. Send only the
`NEXT_QUESTION` it prints — `close` — and move straight
into the close step below (this one has no separate question to send;
"close" means do the close work now).

## Close: location, then config

**The moment `NEXT_QUESTION` says `close`, do only the three numbered
steps below — nothing else.** Do not open other skills (the daily run
loads them itself), and never ask the owner for a city — not in a reply, not
through any tool. If step 1 hasn't produced a timezone, the answer is its "can't be
scheduled yet" message, not a question back to the owner.

Do not write `pt/config.json` until `NEXT_QUESTION` says `close`:

1. **Read location through Latch's browser** — `chat_status.py --busy`
   first, and again after every `goto`. `plow_browser_open` scoped to
   `["ipapi.co", "ipwho.is", "ifconfig.co"]`, then steps 2–3 of
   `pt-research/references/desks.md` §1 (the provider fallback order and
   which field is the timezone), then `plow_browser_close`. If no provider
   loads, or none gives a usable IANA timezone, say the paper cannot be
   scheduled until the Mac can report where they are — do not invent a
   zone, do not ask them to type one.
2. **Write** `/var/lib/plow/pt/config.json` — with this exact bare
   invocation, never by composing the JSON yourself, never with the write tool:

       /opt/plow/skills/pt-setup/scripts/finalize_setup.py /var/lib/plow/pt/config.json --owner-tz <IANA zone from step 1>

   It reads the draft, stores the hour as the owner named it (in their
   own zone; the scheduler fires every job in that zone),
   validates against the gate **before** anything lands, and prints
   `CONFIG:written` plus the delivery line. On failure it prints why and
   writes nothing: an unfinished interview, an unknown zone, or a gate
   failure. That refusal is the answer — do not hand-write the file
   around it.

   If you want to re-check afterwards, the gate is:

       /opt/plow/skills/pt-shared/scripts/pt_config_gate.py /var/lib/plow/pt/config.json

   **Paste the gate's output verbatim.** Empty output is pass. Then run
   `/opt/plow/skills/pt-dashboard/scripts/register_crons.py` and
   paste its output. Finally clear the draft — **with this exact bare
   invocation, never a `rm`, never an interpreter, never `os.remove`**:

       record_setup.py /var/lib/plow/pt/config.json --done

   It prints `DRAFT:cleared`. It is idempotent, and it refuses if the
   interview is somehow unfinished (it names what is missing) — that
   refusal is information, not something to work around.

Say the result in CHAT_VOICE, using the hour they named, never the
container's zone or `TZ`. Portuguese:

> 📰 Pronto — seu jornal chega todo dia às 7h. Se quiser, manda um assunto pra eu pesquisar agora.

English:

> 📰 All set — your paper lands every morning at 7:00. Want me to look something up right now?

Swap in the hour they chose. A first research job is still pt-intake's.
