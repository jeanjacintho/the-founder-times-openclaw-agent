"""wiki.py -- The Founder Times' pages in the owner's wiki, over Latch.

The wiki is plow-wiki: an Obsidian vault at ~/Plow/wiki in OKF v0.2, kept by
the `wiki` plugin Latch bundles. The paper owns one root,
projects/theplowtimes (writer `theplowtimes`, this agent's AGENT_ID), and
shares one page, entities/owner/goals.md. Pages move with plow_read_file and
plow_write_file (no approval inside ~/Plow); the CLI runs through
plow_run_command, under whatever approval mode the Mac is in.
"""
from __future__ import annotations

import yaml

from latch_mcp import LatchError, finish_command
from latch_mcp import connect as latch_connect

WIKI = "~/Plow/wiki"
WRITER = "theplowtimes"
ROOT = f"projects/{WRITER}"
OVERVIEW = f"{ROOT}/{WRITER}.md"
EDITIONS = f"{ROOT}/editions"
QA = f"{ROOT}/qa.md"
RESOURCES = f"{ROOT}/resources.md"
GOALS = "entities/owner/goals.md"
SCHEMA = f"_meta/schemas/{ROOT}.md"
PAPER_LINK = f"[The Founder Times](/{OVERVIEW})"


def split_page(text):
    """(frontmatter, body) of an OKF page; a page without frontmatter is ({}, text)."""
    if not text.startswith("---\n"):
        return {}, text
    head, sep, body = text[4:].partition("\n---\n")
    if not sep:
        return {}, text
    return yaml.safe_load(head) or {}, body


def join_page(meta, body):
    head = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
    return f"---\n{head}---\n{body}"


class Wiki:
    def __init__(self, call_tool):
        self._call = call_tool

    def read_path(self, path):
        """A file's text on the Mac, or None when it does not exist."""
        try:
            return self._call("plow_read_file", {"path": path})["content"]
        except LatchError as exc:
            if "ENOENT" in str(exc):
                return None
            raise

    def read(self, rel):
        return self.read_path(f"{WIKI}/{rel}")

    def write(self, rel, text):
        self._call("plow_write_file", {"path": f"{WIKI}/{rel}", "content": text})

    def run(self, *args, write=False):
        """`wiki <args>` through Latch's wiki plugin: (exit_code, output)."""
        params = {"argv": ["wiki", *args], "wait_ms": 60000,
                  "goal": f"Keep The Founder Times' pages in your wiki (wiki {args[0]})"}
        if write:
            params["write_paths"] = [WIKI]
        result = finish_command(
            self._call, self._call("plow_run_command", params), f"wiki {args[0]}",
        )
        return int(result["exit_code"]), str(result.get("output") or "")

    def check(self):
        """`wiki validate`, then `wiki index`. Only a problem on a page this paper
        writes fails it; another agent's page is that agent's to fix."""
        code, out = self.run("validate")
        ours = [line for line in out.splitlines() if line.startswith((ROOT, GOALS))]
        if ours or code not in (0, 1):
            raise LatchError("wiki validate: " + ("; ".join(ours) or out.strip()))
        code, out = self.run("index", write=True)
        if code != 0:
            raise LatchError(f"wiki index: {out.strip()}")


def connect():
    return Wiki(latch_connect().call_tool)
