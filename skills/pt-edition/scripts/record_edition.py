#!/usr/bin/env python3
"""record_edition.py -- put a delivered edition into the owner's wiki.

usage: record_edition.py <run/<id>/edition.json>

Run once the chat leg is out (pt-edition), never before: the wiki records what
the owner received. The day's page is projects/theplowtimes/editions/<date>.md;
each edition that day appends one `## HH:MM edition` block, stamped in the
owner's own zone (`owner_time.owner_now()`), never the container's: the
advisor's card, then every section the owner chose (anything with a
topic_id) with its body, the evidence its research notes hold
(run/<topic_id>/notes.json) and what could not be sourced. Weather,
calendar, mail and sports stay out: they are the day's reads of the owner's
own accounts, and the wiki is every agent's recall.

The page's `priority` frontmatter is the card of the day's chronologically
latest edition (by its own `HH:MM`, not by write order -- two papers can
record out of order, and the earlier one finishing second must not overwrite
a later card with an older one; `priority_at` is that edition's timestamp,
kept only to judge the next write). Its `sections` frontmatter is each topic
id's own record (headline and every sourced claim), merged across the day's
editions. `updated` is monotonic for the same reason: an edition recording
out of order must not move it backward and have the page announce an older
update than the write that already landed. history.py reads both `priority`
and `sections` back as history. After the write, `wiki
validate` and `wiki index`, so the paper's page lists the day.

The renderer already refused a malformed edition.json before delivery, so the
fields it requires are read directly.

Every string that came from research is untrusted, and Obsidian renders the
page's Markdown and HTML on the owner's Mac: an image link is fetched on open,
a forged heading or list item reads as the paper's own. So each one is written
through `_md()` (inline syntax, and line starts, made inert) and each link
through `_url()` (http(s) only) -- the same once-in-code escaping
render_edition.py does for the printed page.

Prints `RECORDED <page>` or `SKIPPED: <why>`. A failure exits non-zero with
`error: edition not recorded — <why>`; the delivery it follows still stands.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pt-shared" / "scripts"))
from owner_chat import home_channel
from latch_mcp import LatchError
from owner_time import owner_now
from pt_paths import pt_home
from wiki import EDITIONS, PAPER_LINK, connect, join_page, split_page
from wiki_setup import ensure

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render_edition import fill_news_desk  # noqa: E402 -- sibling script beside this one

MARK = "<!-- edition {} -->"

# Inline characters that open Markdown, HTML or Obsidian syntax (image, link,
# embed, code, emphasis), escaped wherever they appear. Angle brackets become
# entities, so no renderer can read a tag.
_INLINE = re.compile(r"([\\`*_\[\]!])")
# Obsidian's paired markers: %%comment%%, ==highlight==, ~~strike~~.
_PAIRS = re.compile(r"(%%|==|~~)")
# What a line may start with to become a heading, list, quote or table.
_LINE_START = re.compile(r"^(\s*)([#+\-*>|]|\d+[.)])")


def _md(text, block=False):
    """Research text as inert Markdown. A single-line field folds its newlines."""
    text = str(text if text is not None else "")
    if not block:
        text = " ".join(text.split())
    text = _INLINE.sub(r"\\\1", text)
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = _PAIRS.sub(lambda m: m.group(0)[0] + "\\" + m.group(0)[1], text)
    return "\n".join(_LINE_START.sub(_inert_start, line) for line in text.split("\n"))


def _inert_start(match):
    """`# x` -> `\\# x`; `1. x` -> `1\\. x` (a backslash only escapes punctuation)."""
    indent, marker = match.group(1), match.group(2)
    if marker[0].isdigit():
        return indent + marker[:-1] + "\\" + marker[-1]
    return indent + "\\" + marker


def _url(url):
    """An http(s) link with nothing in it Markdown could read as syntax, else None."""
    url = str(url or "").strip()
    try:
        scheme = urllib.parse.urlsplit(url).scheme.lower()
    except ValueError:
        return None
    if scheme not in ("http", "https"):
        return None
    return urllib.parse.quote(url, safe=":/?#@&=+;,%~-._!$'*")


def _link(url):
    return _url(url) or "unlinked source"


def _card(card):
    lines = ["### The advisor's desk", "", f"**{_md(card['headline'])}**", ""]
    for rank, recommendation in enumerate(card["recommendations"], 1):
        lines += [f"### {rank}. {_md(recommendation['headline'])}", "", _md(recommendation["body"], block=True), "",
                  f"- First step: {_md(recommendation['first_step'])}"]
        for evidence in recommendation["evidence"]:
            lines.append(f"- Evidence: {_md(evidence['claim'])} ({_md(evidence['source'])})")
        advisor = recommendation["advisor"]
        lines += [f'- Advisor: "{_md(advisor["quote"])}" — {_md(advisor["name"])} ({_link(advisor["url"])})', ""]
    lines += [f"- Question: {_md(question)}" for question in card.get("questions") or []]
    return lines + [""]


def _card_urls(card):
    for recommendation in card["recommendations"]:
        url = _url((recommendation.get("advisor") or {}).get("url"))
        if url:
            yield url


def _archive_card(card, headline):
    """Keep advisor citations, but never persist private evidence locators."""
    recommendations = [
        {**item, "evidence": [{k: v for k, v in evidence.items() if k != "url"}
                               for evidence in item["evidence"]]}
        for item in card["recommendations"]
    ]
    return {**card, "headline": headline, "recommendations": recommendations}


def _section(section, notes):
    lines = [f"### {_md(section['title'])}", ""]
    if section.get("headline"):
        lines += [f"**{_md(section['headline'])}**", ""]
    lines += [_md(section["body"], block=True), ""]
    lines += [f"- {_md(note['claim'])} ({_link(note['url'])})" for note in notes.get("notes") or []]
    lines += [f"- Could not source: {_md(gap)}" for gap in notes.get("could_not_source") or []]
    return lines + [""]


def _section_record(section, notes, prior):
    """This section's structural frontmatter entry: its latest headline and every
    sourced claim, merged with what an earlier edition the same day already recorded.
    A later edition with no headline of its own does not blank out one already known."""
    printed = list(prior.get("printed") or [])
    seen = {(p["claim"], p["url"]) for p in printed}
    for note in notes.get("notes") or []:
        pair = (note["claim"], note["url"])
        if pair not in seen:
            printed.append({"claim": note["claim"], "url": note["url"]})
            seen.add(pair)
    headline = section.get("headline") or prior.get("headline") or ""
    return {"headline": headline, "printed": printed}


def _is_latest_edition(prior_at, now):
    """Whether `now` is the day's newest edition time seen so far.

    Two papers of the same day (the daily job and a focused pt-paper-HHMM,
    say) can finish recording out of order -- an earlier delivery landing
    its write after a later one already has. Judging by edition time rather
    than write order keeps `priority` the latest card regardless (issue #48).
    An unset or unparseable prior_at has nothing to lose to -- absent on a
    page from before this field existed, and possibly mangled by the
    owner's own edit (issue #48 notes the page is meant to be hand-edited in
    Obsidian): a corrupt sentinel refusing every future write would be worse
    than the mis-citation this function exists to fix.
    """
    if not prior_at:
        return True
    try:
        return now >= datetime.fromisoformat(prior_at)
    except (ValueError, TypeError):
        # ValueError: not an ISO string at all. TypeError: parsed but naive
        # (no offset) against an aware `now` -- an owner typing a date by
        # hand is a likelier source than a fresh guess at the missing zone.
        return True


def record(wiki, edition_json, chat, now):
    run_dir = Path(edition_json).parent
    raw = Path(edition_json).read_bytes()
    edition = json.loads(raw)
    fill_news_desk(edition)
    sections = edition.get("sections") or []
    printed = next((s for s in sections if isinstance(s.get("priority"), dict)), None)
    news = [s for s in sections if s.get("topic_id") and s.get("desk") == "news"]
    if printed is None and not news:
        return "SKIPPED: no advisor's card and no section of the owner's"
    rel = f"{EDITIONS}/{edition['date']}.md"
    mark = MARK.format(hashlib.sha256(raw).hexdigest()[:12])
    ensure(wiki, chat)

    # Two papers (the daily job and a focused pt-paper-HHMM, say) hold
    # different run locks and can land here at the same moment; this file
    # lock serializes the day page's read-append-write between them.
    lock_path = pt_home() / "record-edition.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        existing = wiki.read(rel)
        already = existing is not None and mark in existing
        if not already:
            if existing is None:
                meta = {"type": "Edition", "title": f"The Founder Times, {edition['date']}",
                        "description": "", "category": "projects", "tags": ["edition"],
                        "paper": PAPER_LINK, "date": edition["date"], "sources": [],
                        "created": now.isoformat(timespec="seconds")}
                body = f"# The Founder Times, {edition['date']}\n"
            else:
                meta, body = split_page(existing)
            sections_meta = meta.setdefault("sections", {})

            lines, urls = [f"## {now:%H:%M} edition", mark, ""], []
            card = _archive_card(
                {k: v for k, v in printed["priority"].items() if k != "today"},
                printed["headline"],
            ) if printed else None
            if card:
                lines += _card(card)
                urls += list(_card_urls(card))
            for section in news:
                path = run_dir.parent / section["topic_id"] / "notes.json"
                notes = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
                lines += _section(section, notes)
                urls += [_url(note["url"]) for note in notes.get("notes") or []]
                urls += [_url(u) for u in section.get("sources") or []]
                sections_meta[section["topic_id"]] = _section_record(
                    section, notes, sections_meta.get(section["topic_id"], {}))

            cited = {s["resource"] for s in meta["sources"]}
            meta["sources"] += [{"resource": u} for u in dict.fromkeys(urls) if u and u not in cited]
            meta["sources"] = meta["sources"] or [{"resource": f"plow-chat:{chat}"}]
            if card and _is_latest_edition(meta.get("priority_at"), now):
                meta["description"] = card["recommendations"][0]["headline"]
                meta["priority"] = card
                # Full precision: two edits landing under the same second's
                # truncation would otherwise compare equal and let whichever
                # writes second win regardless of which was actually later.
                meta["priority_at"] = now.isoformat()
            elif not meta.get("description"):
                meta["description"] = news[0].get("headline") or news[0]["title"]
            # Monotonic for the same reason priority_at is: an edition that
            # posted earlier but records after one that posted later (and
            # already recorded) must not move "updated" backward and have
            # the page announce an older update than the write that already
            # landed (srosro-review, contract-drift).
            if _is_latest_edition(meta.get("updated"), now):
                meta["updated"] = now.isoformat(timespec="seconds")
            wiki.write(rel, join_page(meta, body.rstrip("\n") + "\n\n" + "\n".join(lines)))
    # A retry must still finish an earlier check() that failed after the
    # write landed -- the marker means "don't append again", never "don't
    # index again".
    wiki.check()
    if already:
        return f"SKIPPED: {rel} already has this edition"
    return f"RECORDED {rel}"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Put a delivered edition into the owner's wiki.")
    parser.add_argument("edition_json")
    parser.add_argument(
        "--now", default=None,
        help="ISO8601 moment this edition was delivered (post_to_chat.py passes the "
             "timestamp it captured right before the chat POST, under the same "
             "delivery-order lock, so a slow print or record step run afterward "
             "cannot masquerade as a later edition). Defaults to owner_now() -- "
             "a manual, standalone run.",
    )
    args = parser.parse_args(argv)
    try:
        now = datetime.fromisoformat(args.now) if args.now else owner_now()
    except ValueError as exc:
        sys.exit(f"error: --now {args.now!r} is not ISO8601 ({exc})")
    try:
        print(record(connect(), args.edition_json, home_channel(), now))
    except (LatchError, OSError, ValueError, KeyError, TypeError) as exc:
        sys.exit(f"error: edition not recorded — {exc}")


if __name__ == "__main__":
    main()
