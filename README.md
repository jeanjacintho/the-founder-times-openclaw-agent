# The Founder Times (inspired by Mayfield)

Your morning paper, printed. It researches on your Mac and puts a sourced page
in the tray — PDF in chat if you'd rather.

An [OpenClaw](https://github.com/openclaw/openclaw) agent on
[Plow Chat](https://howto.plow.co/). You text it like a newspaper, not like a
chatbot. It is one person's paper: the sections you asked for, at the hour you
named, in the language you write.

## What it is

The product is a **compact Letter paper**. It can open with **what Patrick
Salyer would tell you** after watching your last day, learned from your Mac,
then weather, one calendar rail, and up to three stories you told it to cover.
The longest story leads; the other two sit side by side. A dense edition may
continue onto a second sheet. It goes to a printer on your Mac when one is
there, and the same edition lands as a PDF in chat. Mail and sports stay in
the chat edition and research context; they do not compete for printed space.

You do not fill a profile. The first message is the paper: what time it should
arrive. It learns your timezone from where the Mac is.

Research runs on **your** browser, through [Latch](https://howto.plow.co/latch).
If a page cannot be read, the paper says so — it does not invent the paragraph.

What it prints goes into your wiki at `~/Plow/wiki` (Latch's Obsidian-style
wiki): a page for each paper that carried the advisor's card or one of your own
sections, with its sources (never your mail, calendar or weather), your goals,
and the advisor's notes. Open it in Obsidian; edit anything.

It reports. It does not act on what it finds: no purchases, no bookings, no
logins, no downloads.

## What goes in the paper

- **Printed desks** at the front: the advisor's desk (three ranked, sourced
  recommendations challenged by independent critics, using your mail,
  messages, calendar and the sources you name), weather, and one calendar
  rail. Mail and sports stay chat-only. Set `delivery.lead_minutes` for the
  advisor's overnight window; each paper starts no earlier than midnight of its
  delivery day and the PDF waits for the delivery hour before posting.
- **Sections** you named ("esportes", "the dollar", a beat of your own),
  including a different paper at a different hour if you ask for one.
- **One day's assignment** ("put the iPhone price in tomorrow's paper").
- **A one-off** you want once, on a short budget.

Ask in the chat. The edition comes back as its own delivery, on the clock you
set — "send it now" included — never as a live essay in the same turn.

## Install (local)

You need Git, Docker Compose, and [plow-agents](https://github.com/plow-pbc/plow-agents).

```sh
git clone https://github.com/jeanjacintho/the-founder-times-openclaw-agent.git
cd the-founder-times-openclaw-agent

plow-agents login                 # text the printed code
plow-agents lines                 # pick a free line
plow-agents mint LINE_UID         # writes ./plow-credentials before the first up
docker compose up --build -d
docker compose logs -f agent      # wait for: plow-boot: identity resolved … and [gateway] ready
```

Text the line you minted. The first message is the paper's hour, not a profile
interview.

```sh
docker compose down          # stop, keep the paper, sessions and schedule
docker compose down -v       # wipe the state volume (fresh setup)
plow-agents revoke           # retire the line in plow-credentials
```

`plow-credentials` is gitignored. Do not commit it.

## Deploy (cloud)

Build and push the image to a registry you control that Plow can pull, then
deploy it by digest:

```sh
plow-agents image build REGISTRY/REPOSITORY:TAG
plow-agents image push REGISTRY/REPOSITORY:TAG
plow-agents deploy REGISTRY/REPOSITORY@sha256:DIGEST --line LINE_UID
```

A cloud host injects the credentials; there is no `plow-credentials` file.
The image lists itself on the [Agent Index](https://aiworthusing.com/agent-index)
as `thefoundertimes` (`AGENT_ID`, `AGENT_NAME`, `AGENT_BLURB` in the Dockerfile)
and reports its token usage through the base's pinned reporter.

## Your Mac: Latch, the printer and the wiki

Run [Latch](https://howto.plow.co/latch) on the Mac this agent should drive,
signed in to the same Plow account. The agent reaches it with its own
credential — nothing to paste, no restart. Chat works without Latch; research,
the printer and the wiki do not. If the Mac sleeps, the paper says what it
could not source, and a print that cannot reach the printer is reported in
chat in your language.

The printer is whatever CUPS on the Mac calls it (`lpstat -p`); setup asks
once. The wiki is `~/Plow/wiki/projects/thefoundertimes/`.

## How it runs

- **Chat.** The owner's phone DM is the agent's main session. Before each of
  the owner's turns the Plow channel runs the setup gate and hands the model
  its answer; groups are only listened to for priority signals and never
  get replies or setup questions.
- **Schedule.** Every paper is an OpenClaw scheduler job
  (`openclaw cron`), registered by `pt-dashboard/scripts/register_crons.py`
  from your topics: an isolated turn on the chat's own model, in **your**
  timezone (`--tz`), with no automatic delivery — the paper posts itself as a
  PDF. Jobs live in the state volume and survive restarts and
  `docker compose up --build`; on a fresh volume, setup (or any schedule
  change in chat) registers them again.
- **Scripts.** The `pt-*` skills' Python scripts run on Python 3.13 with
  WeasyPrint in a root-owned venv (`/opt/plow/pt-venv`). The paper's state is
  `/var/lib/plow/pt` (config, topics, run scratch).

## Model

Every install runs on Plow's GPT-6 Sol (`plow/openai/gpt-6-sol`). A
one-click install has nothing to configure and never leaves it. The paper's
research runs are long tool loops: on Luna they gave up before research, on
Sol they finish.

The owner of one install can move all of its inference (chat, sub-agents
and the scheduled papers) to their own OpenAI account. In a login shell on
the agent (`docker compose exec agent bash -l`, or SSH on the VM):

```sh
plow-llm openai
```

It signs in with a device code, checks that the account offers
`gpt-6-sol` (the model an OpenAI account runs on: the paper's long research
runs finish on Sol, and gave up on Luna), leaves a marker in the state volume,
and registers the paper's jobs again under the new model. Restart the agent to apply it. The sign-in
and the marker live in the state volume, so rebuilds and image updates keep
them. `plow-llm plow` moves back, and `plow-llm status` shows what the next
boot will choose.

Plow stays configured as the fallback, Sol first and then Luna: a spent
quota or an expired sign-in answers from Plow instead of failing, and Plow's
Luna answers if Plow cannot serve Sol. `AGENT_PROVIDER` (`plow`,
`openai`, `openrouter`) and `AGENT_MODEL` choose a provider from the
environment instead and outrank the marker; OpenAI then takes
`OPENAI_API_KEY` or the sign-in, and OpenRouter `OPENROUTER_API_KEY`. After
changing them, restart and run `plow-llm sync` to move the scheduled jobs.

The sign-in is a real credential for your account, kept in the state volume
where the agent's own tools can read it. Use it on an install only you
talk to.

## Groups, email and trust

Groups the agent starts from the owner's main DM are untrusted by default;
`PLOW_THREAD_TRUST=ask|trusted|untrusted` chooses the policy, and
`plow_set_thread_trust` changes one group later. In an untrusted text
conversation a non-owner gets replies only, no tools; a trusted group's
members get the room's full tools. Groups the agent only listens to keep their
one tool, `plow_record_signal`, whatever their trust. Non-owner senders carry
their normalized phone number or email address as the sender id, so one person
is one sender across chats; the owner is `plow-owner`.

An email turn's final text never reaches the sender: it goes privately to the
owner (the chat the thread was started from, else their 1:1), and mail is sent
only with `plow_send_email`. A turn on mail from anyone but the owner has no tools, so
an email cannot make the assistant send; the owner approves in their chat and
the send comes from their turn. Each outside sender in a thread runs in a session of their own, so
their mail cannot join a run the owner is in. This image does not enable OpenClaw's native
`automations` reminders; the paper's own jobs are registered by
`register_crons.py`.

## Moving a paper from the Hermes edition

The owner's wiki lives on their Mac and does not move. The paper's own
choices — `pt/config.json` and `pt/topics.json` in the old `agent-home`
volume — can be brought over instead of answering setup again:

```sh
# From the Hermes checkout, with its agent still defined:
docker compose cp agent:/var/lib/hermes/pt ./hermes-pt

# From this checkout, with this agent running:
docker compose cp ./hermes-pt agent:/tmp/hermes-pt
docker compose exec -u root agent chown -R node:node /tmp/hermes-pt
docker compose exec agent /opt/plow/skills/pt-setup/scripts/import_state.py \
  --from /tmp/hermes-pt --previous-tz America/Sao_Paulo
```

`--previous-tz` is the `TZ` the old compose ran with (`PT_TZ`, default
`America/Sao_Paulo`). The script refuses a config that fails the setup gate,
a topic store of the wrong shape, or an install that already has a paper
(`--replace` overwrites on purpose), then registers the jobs. Scratch, locks
and the old scheduler's jobs stay behind.

## Known limitations

- If the model provider is unreachable at a job's time, OpenClaw records the
  run as skipped and tries again only at the job's next time: that day's paper
  does not come by itself. Ask for it in chat ("send the paper now") once the
  provider answers.
- An edition delivered while the Mac is unreachable is not recorded in the
  wiki, and the next morning's advisor has no "yesterday" for it.
- One-shot jobs can be scheduled at most ten years ahead.

## Layout

- `boot/`, `plugin/`, `prompt/` — the OpenClaw base: identity, gateway config,
  Plow channel (with the setup-gate hook) and the agent prompt.
- `skills/pt-*` — setup, intake, research, priority, edition, print, dashboard
  and the shared scripts behind them. `skills/owners-mac`,
  `skills/google-workspace` come from the base.
- `tests/*.test.ts` — boot and plugin tests (`node --test`); `tests/pt/` —
  newspaper tests and the repo contract (`pytest`).
- `index/` — Agent Index images, shot from the synthetic `index/edition.json`.

## Development

Tests need no Plow credentials and no network beyond fetching pinned tools.

```sh
npm ci
npm run test:py   # newspaper scripts: pytest on Python 3.13 via uv
npm test          # the above, then the base's tsc, node tests and offline probe in the image
```

The OpenClaw runtime is pinned to `2026.9.6` by image digest, as in the base.

## License

MIT. See [LICENSE](LICENSE).
