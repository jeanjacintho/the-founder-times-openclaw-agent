---
name: pt-print
description: Best-effort paper delivery — ship the edition PDF the chat already got to the owner's printer through Latch when pt/config.json says printer.configured. Invoked by post_to_chat.py after the chat POST, not by the model. Never a delivery requirement: every failure here ends with the chat edition as the outcome.
---

# pt-print — the paper edition, best-effort

**The chat edition is the contract; paper is the bonus.** No failure here
blocks a delivery, re-runs research, or delays the chat edition — it only
costs the page.

## Who runs it

`post_to_chat.py` runs this after every chat POST (`pt-edition` step 2) on
the run's `edition.pdf` — after the text fallback too, where a missing PDF
is a reported miss; a second invocation would double-print. The one command it runs:

    /opt/plow/skills/pt-print/scripts/print_edition.py /var/lib/plow/pt/run/<id>/edition.pdf /var/lib/plow/pt/config.json

It reads `pt/config.json` itself: unless `printer.configured` is exactly
`true` it prints `skipped: printer.configured is not true` and exits 0, and
that skip is silence. Otherwise it writes the same `edition.pdf` the chat
got through Latch and runs `lp` on the Mac; the Mac path, the CUPS name,
pending-handle polling and the AppleScript retry all live in that script.
The page never passes through a tool argument.

## When it fails — and it is allowed to

Any failure — the Mac unreachable, the write denied, `lp` non-zero, "no
such printer", no PDF because the run fell back to text, the script exiting
non-zero or running past 10 minutes — ends the same way:

- the chat edition already delivered is the outcome; say nothing that
  implies the whole delivery failed,
- `post_to_chat.py` posts the one line itself ("page not printed — <reason>;
  next scheduled run retries"); do not repeat it,
- do not retry in a loop, do not queue the page, do not re-run research to
  "fix" it. The next scheduled run recomposes and re-delivers on its own.

A printer that fails on every run is a config problem, not a print problem:
after the second consecutive failed run on a subscription, say the printer
may need re-probing (the pt-setup changing-one-setting path), once, and stop
mentioning it until the owner does something.

## How this reaches the Mac, and what a failure means

`print_edition.py` opens a Latch session through `latch_mcp.connect()`, which
uses one credential on every install: the `PLOW_MCP_URL` and
`PLOW_AGENT_TOKEN` that `plow-init` publishes to every service at boot, having
read this agent's own `mcp_url` from `/v1/agents/me` once. There is no second
path to prefer over it.

That means **there is no state in which paper can never print.** Every
print failure here is one a later run may succeed at:

- the relay answers 404 until Latch connects — the owner opening Latch on
  their Mac fixes it, and the next run prints,
- a sleeping Mac, an off printer, a `lp` refusal — all recoverable.

So never tell the owner this install cannot print; it can.
And do not send them to relink a Latch pairing without reading its state
first — a failure here is far more often the Mac being asleep than the
pairing being broken.
