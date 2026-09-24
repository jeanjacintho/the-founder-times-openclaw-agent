"""Loaders for the pt- scripts under test.

The scripts are plain files beside the skills that run them (no package, no
install), so each suite loads them by path -- the same realpath resolution
the cross-skill imports use inside the container.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pt-shared" / "scripts"))

from latch_mcp import LatchError


def load_module(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeMac:
    """The owner's Mac as Latch shows it to a script: files under a tmp home, and
    the real `wiki` CLI (the plow-wiki the justfile pins) run where the plugin runs it."""

    def __init__(self, home):
        self.home = pathlib.Path(home)
        self.asleep = False

    def mac_path(self, path):
        return self.home / path[2:] if path.startswith("~/") else pathlib.Path(path)

    def call_tool(self, name, args):
        if self.asleep:
            raise LatchError("Mac unreachable")
        if name == "plow_read_file":
            path = self.mac_path(args["path"])
            if not path.exists():
                raise LatchError(f"read failed: ENOENT: no such file or directory, stat '{path}'")
            return {"path": str(path), "content": path.read_text(encoding="utf-8")}
        if name == "plow_write_file":
            path = self.mac_path(args["path"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
            return {"status": "completed", "path": str(path)}
        if name == "plow_run_command" and args["argv"][0] == "wiki":
            argv = [str(self.mac_path(a)) if a.startswith("~/") else a for a in args["argv"]]
            env = {**os.environ, "HOME": str(self.home),
                   "WIKI_PATH": str(self.home / "Plow" / "wiki")}
            done = subprocess.run(argv, capture_output=True, text=True, env=env)
            return {"exit_code": done.returncode, "output": done.stdout + done.stderr}
        raise AssertionError(f"FakeMac has no {name} {args}")

    def wiki(self, *args):
        """Run the CLI on the Mac's wiki directly (test setup and oracle checks)."""
        return self.call_tool("plow_run_command", {"argv": ["wiki", *args]})


@pytest.fixture
def mac(tmp_path):
    return FakeMac(tmp_path / "home")
