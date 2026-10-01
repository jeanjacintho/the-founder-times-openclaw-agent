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
        assert Wiki(mac.call_tool).read("projects/thefoundertimes/nope.md") is None

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

    @pytest.mark.parametrize("rel, meta, field", [
        (f"{ROOT}/x.md", {"description": None}, "description"),
        (f"{ROOT}/runs/2026-10-01T0331/state.md", {"type": "Synthesis", "sources": None}, "sources"),
        (GOALS, {"type": "Owner", "category": "entities", "description": None}, "description"),
    ])
    def test_check_fails_on_a_broken_page_of_ours(self, mac, rel, meta, field):
        declare_root(mac)
        w = Wiki(mac.call_tool)
        w.write(rel, page(**meta))
        with pytest.raises(LatchError, match=rf"{rel}: missing required field: {field}"):
            w.check()

    @pytest.mark.parametrize("rel, meta", [
        ("entities/people/someone.md", {"type": "Person", "category": "entities"}),
        ("projects/str/x.md", {}),
    ])
    def test_check_ignores_another_writers_broken_page(self, mac, rel, meta):
        declare_root(mac)
        toml = mac.home / "Plow" / "wiki" / "wiki.toml"
        toml.write_text(toml.read_text() + '\n[roots."projects/str"]\nwriter = "str"\n')
        mac.wiki("init", "~/Plow/wiki")
        w = Wiki(mac.call_tool)
        w.write(rel, page(description=None, **meta))
        w.write(GOALS, page(type="Owner", category="entities"))
        w.check()

    def test_check_refuses_a_wiki_that_does_not_declare_our_root(self, mac):
        mac.wiki("init", "~/Plow/wiki")
        with pytest.raises(LatchError, match=rf"--writer {WRITER}: no root in wiki.toml"):
            Wiki(mac.call_tool).check()
