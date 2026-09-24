#!/usr/bin/env python3
"""record_owner_language.py — the only way live chat updates owner.language.

Measured live (2026-09-18): setup and the first papers ran in English.
One Portuguese request ("Quero uma nova versão do jornal") patched
pt/config.json to Portuguese by a free-form edit. Two later English
requests ("Yes, I want a version to read now") left it Portuguese:
pt-intake said "update if it differs" but that was a hand-edit, and
READY printed no LANG line, so the model followed the stored language.

This script is the mechanical write. pt-intake names the language of
THIS owner message (plain-English name) and runs:

    record_owner_language.py /var/lib/plow/pt/config.json English

Skip the call only when the message is a lone acknowledgement
(yes / y / ok / sim / no / não) with no other words.

While setup is unfinished it writes `.setup-draft.json` (same sibling
as record_setup.py). After READY it writes `pt/config.json`. Prints
LANG:<language> on success, then PHRASES:missing when that language has no
fixed phrases yet (owner_phrases.py: write them before answering).

Exit 0 on success. Missing args or a blank language: stderr, exit 1.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import setup_needed as _gate  # noqa: E402
from pt_paths import config_file  # noqa: E402
from owner_phrases import status as phrases_status  # noqa: E402

DEFAULT_CONFIG = str(config_file())


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _load_json(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(config_path, language):
    """Write owner.language to draft (setup) or config (READY). Return LANG line."""
    language = (language or "").strip()
    if not language:
        raise ValueError("language is blank")
    config_path = Path(config_path)
    path = (
        config_path.with_name(".setup-draft.json")
        if _gate.setup_needed(config_path)
        else config_path
    )
    data = _load_json(path)
    owner = data.get("owner")
    if not isinstance(owner, dict):
        owner = {}
        data["owner"] = owner
    if owner.get("language") == language:
        return "LANG:" + language
    owner["language"] = language
    _write_json(path, data)
    return "LANG:" + language


def main(argv=None):
    argv = sys.argv if argv is None else argv
    if len(argv) != 3:
        print(
            "usage: record_owner_language.py <config.json path> <language>",
            file=sys.stderr,
        )
        return 1
    try:
        line = record(argv[1], argv[2])
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(line)
    # A language with no curated lines needs the paper's fixed phrases written
    # once, in it (owner_phrases.py); English and Portuguese never do.
    if phrases_status(argv[2].strip()) == "missing":
        print("PHRASES:missing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
