"""wiki.py: the paper's pages in the owner's wiki, checked by the real plow-wiki."""
from __future__ import annotations

import pytest

from latch_mcp import LatchError
from wiki import GOALS, ROOT, WRITER, Wiki, join_page, split_page


def declare_root(mac):
    mac.wiki("init", "~/Plow/wiki")
    toml = mac.home / "Plow" / "wiki" / "wiki.toml"
    toml.write_text(toml.read_text() + f'\n[roots."{ROOT}"]\nwriter = "{WRITER}"\n')
    mac.wiki("init", "~/Plow/wiki")  # writes the root's base schema


def page(**meta):
    base = {"type": "Project", "title": "T", "description": "D", "category": "projects",
            "tags": [], "sources": [{"resource": "plow-chat:cht_1"}],
            "created": "2026-09-19", "updated": "2026-09-19"}
    return join_page({**base, **meta}, "# T\n")


class TestPageFormat:
    def test_join_then_split_returns_the_same_page(self):
        meta = {"type": "Edition", "priority": {"headline": "Call Raj", "who": ["Raj — cousin"]},
                "time": "10:00"}
        assert split_page(join_page(meta, "# Body\n\n- a\n")) == (meta, "# Body\n\n- a\n")

    def test_a_page_without_frontmatter_is_all_body(self):
        assert split_page("# Just notes\n") == ({}, "# Just notes\n")


class TestWiki:
    def test_a_missing_page_reads_as_none(self, mac):
        assert Wiki(mac.call_tool).read("projects/theplowtimes/nope.md") is None

    def test_a_write_reads_back(self, mac):
        w = Wiki(mac.call_tool)
        w.write(f"{ROOT}/x.md", "hello\n")
        assert w.read(f"{ROOT}/x.md") == "hello\n"

    def test_check_passes_and_indexes_a_valid_wiki(self, mac):
        declare_root(mac)
        w = Wiki(mac.call_tool)
        w.write(f"{ROOT}/x.md", page())
        w.check()
        assert (mac.home / "Plow" / "wiki" / "index.md").exists()

    def test_check_fails_on_a_broken_page_of_ours(self, mac):
        declare_root(mac)
        w = Wiki(mac.call_tool)
        w.write(f"{ROOT}/x.md", page(description=None))
        with pytest.raises(LatchError, match=rf"{ROOT}/x.md: missing required field: description"):
            w.check()

    def test_check_ignores_another_agents_broken_page(self, mac):
        declare_root(mac)
        w = Wiki(mac.call_tool)
        w.write("entities/people/someone.md", page(type="Person", category="entities", description=None))
        w.write(GOALS, page(type="Owner", category="entities"))
        w.check()
