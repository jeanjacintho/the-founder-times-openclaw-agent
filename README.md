# The Founder Times (inspired by Mayfield)

Your morning paper, printed. It researches on your Mac and puts a sourced page
in the tray — PDF in chat if you'd rather.

This repository moves The Founder Times from Hermes onto the Plow base image for
OpenClaw. It is a fork of
[plow-openclaw-agent](https://github.com/plow-pbc/plow-openclaw-agent) that adds
Python and WeasyPrint for the newspaper skills in `skills/pt-*`, the Opus 5
model and the OpenClaw scheduler for the daily edition.

**Status: migration in progress.** Behaviour parity with the Hermes edition comes
first; the install guide is written once parity is reached.

## Layout

- `boot/`, `plugin/`, `prompt/` — the OpenClaw base: identity, gateway config,
  Plow channel and the agent prompt.
- `skills/pt-*` — setup, intake, research, priority, edition, print, dashboard
  and the shared scripts behind them.
- `tests/*.test.ts` — base tests (`node --test`); `tests/pt/` — newspaper tests
  (`pytest`).
- `index/` — Agent Index images.

The Agent Index reporter from the base is kept as is (`AGENT_ID=theplowtimes`).

## License

MIT. See `LICENSE` and `NOTICE`.
