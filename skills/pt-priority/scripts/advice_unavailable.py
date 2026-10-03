#!/usr/bin/env python3
"""advice_unavailable.py -- the only writer of an "advice unavailable" card, and its proof.

Measured live 2026-09-30: the 07:00 paper had 148 minutes before 09:30, read
the owner's goals, then wrote "the three generations could not be completed"
into run/desk-priority/notes.json without starting one critic. The card said
the tournament failed; it never ran. So the desk no longer writes that file
by hand: this script writes it, and only with a reason it can check.

  window  --deliver-at HH:MM --reason TEXT
      too little time: the paper took today's paper-workspace lock under 50
      minutes before HH:MM. Refused when the window was 50 minutes or more.
  blocked --reason TEXT
      Orient could not reach the owner's wiki. Runs `wiki_setup.py --desk`
      itself; refused when that succeeds, and the renderer runs it again.

A tournament that started and reached no accepted checkpoint has no reason
here: the paper fails loudly instead of printing an unavailable card.

Every kind needs today's lock (the paper that owns the desk holds it), and the
skip records that lock's timestamp: desk-priority survives a later paper's
--preserve-priority, and a reason one paper proved is not proof for the next.
On success it writes `{"date", "could_not_source": [reason], "skip": {...}}`
and prints `ADVICE:unavailable <kind>`; a refusal exits non-zero with the
reason and writes nothing. render_edition.py re-checks the same proof with
proof_problem() before it prints the card.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pt-shared" / "scripts"))
from owner_time import HHMM, owner_now  # noqa: E402
from pt_paths import pt_home  # noqa: E402
import run_lock  # noqa: E402

# pt-priority/SKILL.md Orient: three generations need about 50 minutes.
MIN_TOURNAMENT_MINUTES = 50
KINDS = ("window", "blocked")
WORKSPACE_LOCK = "paper-workspace"
WIKI_SETUP = Path(__file__).resolve().parents[2] / "pt-shared" / "scripts" / "wiki_setup.py"


def today():
    return owner_now().date().isoformat()


def owner_zone():
    return str(owner_now().tzinfo)


def lock_taken_at(run_root, day):
    """When this paper took today's paper-workspace lock, or None."""
    return run_lock.taken_at(run_root, f"{WORKSPACE_LOCK}-{day}")


def window_minutes(taken, day, deliver_at, tz):
    """Whole minutes from taking the lock to HH:MM of the owner's `day`."""
    match = HHMM.match(deliver_at or "")
    if not match:
        raise ValueError(f"not an HH:MM time: {deliver_at!r}")
    year, month, date_ = (int(part) for part in day.split("-"))
    target = datetime(year, month, date_, int(match.group(1)), int(match.group(2)),
                      tzinfo=ZoneInfo(tz))
    return int((target - taken).total_seconds() // 60)


def wiki_check():
    try:
        done = subprocess.run([sys.executable, str(WIKI_SETUP), "--desk"],
                              capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return 1, "wiki_setup.py --desk timed out"
    lines = (done.stdout + done.stderr).strip().splitlines()
    return done.returncode, (lines[-1] if lines else "")


def proof_problem(notes, run_root, day, tz, wiki_fn=None):
    """Why an unavailable card is not proven, or None when it is."""
    skip = notes.get("skip") if isinstance(notes, dict) else None
    if not isinstance(skip, dict) or skip.get("kind") not in KINDS:
        return ("desk-priority/notes.json was not written by advice_unavailable.py; "
                "run the tournament, or record why it cannot run with that script")
    taken = lock_taken_at(run_root, day)
    if taken is None:
        return "this paper does not hold today's paper-workspace lock"
    if run_lock.parse_stamp(str(skip.get("lock") or "")) != taken:
        return ("desk-priority/notes.json was recorded under another paper's lock; "
                "this paper must run the tournament or record its own reason")
    if skip["kind"] == "window":
        try:
            minutes = window_minutes(taken, day, skip.get("deliver_at"), tz)
        except ValueError as exc:
            return str(exc)
        if minutes >= MIN_TOURNAMENT_MINUTES:
            return (f"the paper took the lock {minutes} minutes before {skip['deliver_at']}, "
                    f"enough for the tournament ({MIN_TOURNAMENT_MINUTES}); run the tournament")
    else:
        if not str(skip.get("check") or "").strip():
            return "a blocked desk carries no failed check"
        if (wiki_fn or wiki_check)()[0] == 0:
            return "wiki_setup.py --desk succeeds now; the desk is not blocked -- run the tournament"
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="kind", required=True)
    window = sub.add_parser("window", help="too little time before the delivery hour")
    window.add_argument("--deliver-at", required=True)
    sub.add_parser("blocked", help="the owner's wiki cannot be reached")
    for p in sub.choices.values():
        p.add_argument("--reason", required=True, help="the owner-language line the card prints")
    args = parser.parse_args(argv)

    day, run_root = today(), pt_home() / "run"
    taken = lock_taken_at(run_root, day)
    if taken is None:
        sys.exit("error: this paper does not hold today's paper-workspace lock")
    lock = taken.isoformat(timespec="seconds")
    code = last = None
    if args.kind == "window":
        skip = {"kind": "window", "deliver_at": args.deliver_at, "lock": lock}
    else:
        code, last = wiki_check()
        if code == 0:
            sys.exit("error: wiki_setup.py --desk succeeded; the desk is not blocked -- run the tournament")
        skip = {"kind": "blocked", "check": last, "lock": lock}
    notes = {"date": day, "could_not_source": [args.reason], "skip": skip}
    problem = proof_problem(notes, run_root, day, owner_zone(), lambda: (code, last))
    if problem:
        sys.exit(f"error: {problem}")
    path = run_root / "desk-priority" / "notes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(notes, ensure_ascii=False), encoding="utf-8")
    print(f"ADVICE:unavailable {args.kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
