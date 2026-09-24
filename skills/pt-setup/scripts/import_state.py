#!/usr/bin/env python3
"""Bring an existing paper over from the previous runtime's state volume.

    /opt/plow/skills/pt-setup/scripts/import_state.py --from DIR [--previous-tz ZONE] [--replace] [--no-register]

DIR is a copy of the old agent home (the directory holding `pt/`) or of its
`pt/` directory itself. Only the owner's own choices move: `pt/config.json`
(the delivery hour, printer, desks, language, zone) and `pt/topics.json` (the
sections, subscriptions, one-offs and assignments). Run scratch, locks and
the old scheduler's jobs stay behind -- the jobs are replayed from the topics
by register_crons.py, which this runs last. The owner's wiki lives on their
Mac and never moves.

Refuses, writing nothing, when the config fails the setup gate, when the
topic store is not the shape topics.py writes, or when this install already
has a paper (pass --replace to overwrite it on purpose).

--previous-tz names the old container's TZ (the old compose defaulted to
America/Sao_Paulo). It only matters for a config that still carries
`delivery.local_hour`; register_crons.py then retires that key when the zone
equals owner.timezone, and otherwise asks for the owner's times again.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "pt-shared" / "scripts"))
from pt_config_gate import GateError, gate  # noqa: E402
from pt_paths import pt_home, script  # noqa: E402
from record_owner_language import _write_json  # noqa: E402 -- the config's atomic writer

TOPIC_ID_RE = re.compile(r"^t_[0-9a-f]{4}$")


def _strict_json(path):
    return json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda token: (_ for _ in ()).throw(
        ValueError(f"non-standard JSON constant {token}")))


def source_dir(path):
    path = Path(path)
    if (path / "pt" / "config.json").is_file():
        return path / "pt"
    if (path / "config.json").is_file():
        return path
    raise SystemExit(f"refusing to import: no pt/config.json under {path}")


def read_config(src):
    path = src / "config.json"
    try:
        config = _strict_json(path)
        failures = gate(config)
    except (OSError, ValueError, GateError) as exc:
        raise SystemExit(f"refusing to import: {path} is not valid JSON ({exc})") from None
    if failures:
        raise SystemExit(f"refusing to import: {path} fails the setup gate: {failures}")
    return config


def read_topics(src):
    path = src / "topics.json"
    if not path.exists():
        return []
    try:
        data = _strict_json(path)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"refusing to import: {path} is not valid JSON ({exc})") from None
    topics = data.get("topics") if isinstance(data, dict) else None
    if not isinstance(topics, list) or not all(
            isinstance(t, dict) and TOPIC_ID_RE.fullmatch(str(t.get("id", ""))) for t in topics):
        raise SystemExit(f"refusing to import: {path} is not the {{\"topics\": [...]}} store topics.py writes")
    return topics


def register(previous_tz):
    env = dict(os.environ)
    if previous_tz:
        env["TZ"] = previous_tz
    return subprocess.run([str(script("pt-dashboard", "register_crons.py"))], env=env).returncode


def main(argv=None, register_jobs=register):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="source", required=True)
    parser.add_argument("--previous-tz", default="")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--no-register", action="store_true")
    args = parser.parse_args(argv)

    src = source_dir(args.source)
    config = read_config(src)
    topics = read_topics(src)
    dest = pt_home()
    if (dest / "config.json").exists() and not args.replace:
        raise SystemExit(
            f"refusing to import: {dest / 'config.json'} already exists -- this install has a "
            "paper. Pass --replace to overwrite it.")
    dest.mkdir(parents=True, exist_ok=True)
    _write_json(dest / "topics.json", {"topics": topics})
    _write_json(dest / "config.json", config)
    print(f"imported: {dest / 'config.json'} (delivery {config['delivery']['hour']}, "
          f"zone {config['owner']['timezone']}) and {len(topics)} topic(s)", flush=True)
    if args.no_register:
        return 0
    return register_jobs(args.previous_tz)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
