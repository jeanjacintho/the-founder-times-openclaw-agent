---
name: pt-shared
description: The helper library every pt-* skill imports — the pt-config gate, the bearer-HTTP helpers, the chat delivery POST and the owner's wiki, each script's calling contract one bullet each. Not a task; nothing here is invoked on its own.
---

# pt-shared — the pt-* skills' shared helpers

Every pt-* skill's scripts reach this directory by its absolute deploy path,
`/opt/plow/skills/pt-shared/scripts`, never a `../../` relative path
(a turn's working directory is the agent workspace, not this skill, so a
relative path never resolves). The image bakes every pt-* skill under
`/opt/plow/skills`, root-owned; this one carries a `SKILL.md` so the gateway
lists it beside its siblings. Paths come from `pt_paths.py`, never a literal.

- `scripts/pt_config_gate.py` — the single definition of a valid `pt/config.json`;
  prints failing invariant names, empty stdout is pass
- `scripts/setup_needed.py` — live-chat first-run gate: prints `SETUP_NEEDED`
  then `DRAFT:` and `LANG:`, or `READY` then `LANG:` (from `pt/config.json`;
  missing file is needed)
- `scripts/record_setup.py` — the ONLY way `pt-setup` writes
  `.setup-draft.json`. Call it bare, space-separated, never through an
  interpreter: `record_setup.py <config.json path> key=value [key=value …]`.
  Dotted keys nest; `true`/`false` (any case) become real JSON booleans;
  every other value is kept verbatim as a string, so a dotted or underscored
  value needs no quoting — only a value containing a space does. Prints
  `DRAFT:<fields recorded, or "none">` then
  `NEXT_QUESTION=<hour|printer|priority|mail|news|close>`; that second line — never
  the draft's shape, never the chat thread — decides what `pt-setup` asks
  next. Called as `record_setup.py <config.json path> --done` it instead
  **clears** the draft (prints `DRAFT:cleared`) — the close step's last
  act, and the only supported way to delete `.setup-draft.json`. It is
  idempotent and refuses an unfinished interview. **This bullet is the contract: it exists so no run ever has to open
  the script to find out how to call it.**
- `scripts/record_owner_language.py` — the ONLY way live chat updates
  `owner.language` after (and during) setup. Bare:
  `record_owner_language.py <config.json path> English`. Prints `LANG:<language>`.
  Setup-unfinished → draft; `READY` → `pt/config.json`. Skip only on a
  lone `yes`/`y`/`ok`/`okay`/`sim`/`no`/`não`/`nao`. **This bullet is the contract.**
- `scripts/pt_paths.py` — the one place that names the paper's paths:
  `pt_home()` (`/var/lib/plow/pt`), `skills()` (`/opt/plow/skills`),
  `config_file()`, `script(skill, name)`; `PT_HOME` / `PT_SKILLS` override
  them for tests. A library, not a command
- `scripts/owner_chat.py` — bare, prints the owner's DM uid:
  `PLOW_HOME_CHANNEL` when boot exported it, else asks `/v1/agents/me` (the
  owner has not texted yet at boot). Every script that posts or records
  calls its `home_channel()`; it exits by name when there is no owner's chat
- `scripts/bearer_http.py` — one bearer JSON call that never follows a redirect
  (a forwarded Authorization header is the credential walking to a host the API
  did not authenticate)
- `scripts/latch_mcp.py` — the one MCP session with the owner's Mac
  (`connect()`, `LatchClient.call_tool` (one stateless request, pending
  handles settled), `LatchError`). A failure raises `LatchError`; the caller
  names what did not happen. The print leg and the wiki scripts both use it.
  `connect()` uses the `PLOW_MCP_URL` / `PLOW_AGENT_TOKEN` the pinned base
  publishes to every service at boot, on both install shapes and with no
  second path to prefer over it.
- `scripts/owner_language.py` — `is_portuguese(language)`, the one place that
  reads `owner.language` for repo-authored copy (the chat wait lines, the
  print-miss line and the priority card's "Advice from" line). A library, not a flow
  script: nothing invokes it, the pt-* scripts import it.
- `scripts/wiki.py` — the paper's pages in the owner's wiki (`~/Plow/wiki`, plow-wiki):
  the root `projects/theplowtimes` (writer `theplowtimes`), the shared
  `entities/owner/goals.md`, the OKF page format, and `check()` = `wiki validate`
  then `wiki index` through Latch's wiki plugin, failing only on the paper's own pages.
- `scripts/wiki_setup.py` — make `~/Plow/wiki` ready for the paper. Bare:
  `wiki_setup.py` or `wiki_setup.py --desk`. Creates the wiki with `wiki init` when
  the Mac has none, writes the paper's schema and page when absent, declares
  `projects/theplowtimes` in `wiki.toml` (appending; no other root is touched), and
  with `--desk` the goals page and the desk's Q&A, carrying an older install's notes
  file over once. Prints `WIKI:ready` or `WIKI:set up …`;
  `error: wiki not ready — …` exits non-zero. **This bullet is the contract.**
- `assets/wiki/` — the seeds `wiki_setup.py` writes: the root's schema (fields and the
  Editions / Your advisors tables), the paper's page, the goals page, the desk's Q&A.
- `scripts/post_to_chat.py` — the edition's chat leg: POST the PDF plus its
  chat-only mail/sports companion when present, or chat text if there is no PDF.
  `--filename The-Founder-Times-<date>.pdf` is the name shown in chat (the
  run file stays `edition.pdf` on disk). `--hold-until HH:MM` waits for
  that clock before posting (scheduled papers; the on-demand copy has none). After
  either POST it prints the run's `edition.pdf` when the printer is configured
  (the text leg too, so a missing PDF is reported as a miss), records
  the edition and finalizes its topics (`pt-edition` step 2).
- `scripts/chat_status.py --busy` — setup's hang-on during pt-setup Latch/Mac
  work (one hang-on, then one "still on it", never a play-by-play). Cron never
  calls it.
- `scripts/owner_time.py` — the owner's own clock, not the container's:
  `owner_now()` (an aware datetime) and `owner_today()`, from `owner.timezone`
  in `pt/config.json`. Falls back to the container's clock only when the
  config or the key is absent; a config that exists but can't be trusted (bad
  JSON, an unreadable file, an unknown zone name) raises. Shared by
  `history.py`'s window, `record_edition.py`'s heading and
  `post_to_chat.py --hold-until`.
- `pt-priority/scripts/history.py recent [--topic ID]` — what this paper printed on the last 7
  days, read from the wiki's edition pages: bare, the advisor desk's cards, `[{"date", "desk"}]`;
  with a news section's topic id, that section's own blocks,
  `[{"date", "headline", "printed": [{"claim", "url"}]}]`, so a pass knows which sources it has
  already spent.
- `pt-edition/scripts/record_edition.py <edition.json>` — the delivered edition onto the day's
  page in the wiki, then `wiki validate` + `wiki index`.
- `scripts/run_lock.py` — one exclusive run per name with stale takeover, so
  two daily-paper runs can never race and deliver a hollow edition.
  Called bare, never through an interpreter:
  `/opt/plow/skills/pt-shared/scripts/run_lock.py acquire --name NAME [--stale-minutes N]`
  and the matching `.../run_lock.py release --name NAME`. Prints one word
  (`acquired` / `stale-takeover` / `held`) and always exits 0 on acquire.
- `scripts/prepare_daily_run.py` — immediately after any paper lock is acquired,
  archives prior dated and desk scratch beside `run/` and prints `READY`.
  Every paper passes `--preserve-priority` (desks.md decides which advisor checkpoint
  is reused); every other desk is cleared.
  It preserves topic workspaces, the live lock, and setup evidence. The wiki is delivered
  history; archived scratch is never today's completed work.
- `scripts/signals.py` — the priority-signal contract (`source`, `from_name`,
  `chat_or_thread_id`, `text`, `received_at`, `category`, `item`) and its
  files under `pt/signals/`; imported, never run.
- `scripts/signal_intake.py` — the ONLY way a signal is written. Called bare
  with one record as JSON on stdin; prints one JSON line. Only
  `category: priority` from a source switched on in `config.json` `signals`
  becomes a file; spam, fyi, duplicates and empty text are refused with a
  `reason`. Never write `pt/signals/` with the write or edit tools.
- `scripts/set_signal_source.py <group_chat|email|imessage> <on|off>` — the
  ONLY way a finished config's signal switches change; gate-checked, atomic,
  prints `SIGNALS:group_chat=…,email=…,imessage=…`. Called bare.
- `references/config.example.json` — the config contract `pt_config_gate.py`
  enforces (including the optional `delivery.lead_minutes`, default 0, and
  optional `mail.configured`, default off)
