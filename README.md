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

## Development

Tests need no Plow credentials and no network beyond fetching pinned tools.

```sh
npm ci
npm run test:py   # newspaper scripts: pytest on Python 3.13 via uv
npm test          # the above, then the base's tsc, node tests and offline probe in the image
```

## License

MIT. See `LICENSE` and `NOTICE`.
