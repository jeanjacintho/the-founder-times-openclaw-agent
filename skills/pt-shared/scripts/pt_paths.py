"""Where the paper lives inside the image -- the one place that says so.

    PT_HOME  /var/lib/plow/pt    config.json, topics.json, run/, locks: the
                                 agent's own state, on the state volume
    SKILLS   /opt/plow/skills    the pt-* skills, root-owned and read-only

Both are absolute because a turn's working directory is not something a
script can trust. `PT_HOME` and `PT_SKILLS` override them (tests point them
at a tmp dir); they are read at call time, not frozen at import, so a test
that sets them after importing a script still moves every path.
"""
from __future__ import annotations

import os
from pathlib import Path

PT_HOME_DEFAULT = "/var/lib/plow/pt"
SKILLS_DEFAULT = "/opt/plow/skills"


def pt_home() -> Path:
    return Path(os.environ.get("PT_HOME") or PT_HOME_DEFAULT)


def skills() -> Path:
    return Path(os.environ.get("PT_SKILLS") or SKILLS_DEFAULT)


def config_file() -> Path:
    return pt_home() / "config.json"


def script(skill: str, name: str) -> Path:
    """Absolute path of one pt- script, e.g. script("pt-shared", "run_lock.py")."""
    return skills() / skill / "scripts" / name
