#!/usr/bin/env python3
"""scan_private_signals.py -- the owner's incoming mail and iMessage, as signal candidates.

    scan     read both sources through Latch, drop what is obviously not a person
             writing to the owner, print the survivors
    commit   after the run has classified them, move the cursor past what scan saw

Every sender is read (there is no trusted list); what keeps spam out is this
filter plus the classification the paper run does next with
pt-shared/references/signal-triage.md, and signal_intake.py, which only ever
writes `priority`.

`scan` prints one JSON object and always exits 0:

    {"candidates": [{source, from_name, chat_or_thread_id, text, received_at, item}],
     "dropped": {"email": {"<reason>": n}, "imessage": {...}},
     "degraded": ["<source>: <why it could not be read>"]}

A candidate is a signal record without `category`: add the category and pass
it to signal_intake.py. A source that could not be read is named in
`degraded` -- never reported as "no mail". Sources switched off in
config.json `signals` are not read at all.

The argv sent to the Mac is the same on every run (a fixed window, cut locally
by the cursor): the Mac's always-allow rules key on the exact argv, so an
unattended run is never left waiting for an approval.

Cursor, in two phases so a run that dies halfway re-reads the same window
(signal_intake.py drops the duplicates): `scan` writes what it saw to
`$PT_HOME/signals/.pending.json`; `commit` makes that the cursor
(`.cursor.json`). A source that failed keeps its previous cursor.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "pt-shared" / "scripts"))
from latch_mcp import LatchError, finish_command  # noqa: E402
from pt_paths import config_file, pt_home  # noqa: E402

GMAIL_QUERY = ("in:inbox newer_than:2d -in:spam -category:promotions -category:social "
               "-category:updates -category:forums")
GMAIL_ARGV = ["plow-gog", "gmail", "search", GMAIL_QUERY, "--max", "25", "--timezone", "UTC",
              "--json", "--fields", "id,date,from,subject"]
IMESSAGE_ARGV = ["plow-messages", "search", "--limit", "200", "--order", "desc"]
IMESSAGE_GOAL = "Read incoming iMessages for the paper's priority signals"
GMAIL_GOAL = "Read incoming mail for the paper's priority signals"
FIRST_LOOKBACK = timedelta(days=2)
MAX_CANDIDATES = 40

AUTOMATED_LOCAL = re.compile(
    r"^(no-?reply|do-?not-?reply|nao-?responda|naoresponda|notifications?|notificacoes|"
    r"mailer-daemon|postmaster|bounces?|newsletters?|news|alerts?|updates?|marketing|info)([+._-].*)?$",
    re.IGNORECASE)
ADDRESS = re.compile(r"<?([^<>\s]+@[^<>\s]+)>?\s*$")
SHORT_CODE = re.compile(r"^\d{3,6}$")
PHONE = re.compile(r"^\+?\d{7,15}$")
CODE_WORDS = re.compile(r"c[oó]digo|code|verifica|OTP|senha|password|token", re.IGNORECASE)
CODE_DIGITS = re.compile(r"\b\d{4,8}\b")


def signals_dir():
    return pt_home() / "signals"


def _read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def enabled_sources():
    config = _read_json(config_file(), {})
    switches = config.get("signals") if isinstance(config, dict) else None
    if not isinstance(switches, dict):
        return set()
    return {source for source in ("email", "imessage") if switches.get(source) is True}


def _address(sender):
    match = ADDRESS.search(sender or "")
    return match.group(1) if match else ""


def _name(sender):
    name = (sender or "").split("<")[0].strip().strip('"')
    return name or _address(sender) or (sender or "").strip()


def email_drop_reason(row):
    local = _address(row.get("from", "")).split("@")[0]
    if local and AUTOMATED_LOCAL.match(local):
        return "automated-sender"
    return None


def imessage_drop_reason(row):
    sender = str(row.get("sender") or "")
    body = str(row.get("body") or "").strip()
    if row.get("is_from_me"):
        return "from-owner"
    if sender.startswith("urn:biz:"):
        return "business"
    if SHORT_CODE.match(sender) or not (PHONE.match(sender) or "@" in sender):
        return "short-code"
    if not body:
        return "empty"
    if CODE_WORDS.search(body) and CODE_DIGITS.search(body):
        return "verification-code"
    return None


def _utc(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)  # gmail dates are asked for in UTC
    return parsed.astimezone(timezone.utc)


def _stamp(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _count(dropped, source, reason, n=1):
    dropped.setdefault(source, {})
    dropped[source][reason] = dropped[source].get(reason, 0) + n


def read_email(call_tool, cursor, dropped):
    """(candidates, seen) -- seen is the thread->date map this window holds."""
    result = call_tool("plow_run_command", {"argv": GMAIL_ARGV, "goal": GMAIL_GOAL})
    if isinstance(result, dict) and "items" not in result and "output" in result:
        result = finish_command(call_tool, result, "gmail search")
        if int(result.get("exit_code", 1)) != 0:
            raise LatchError(f"gmail search exited {result.get('exit_code')}")
        result = json.loads(result.get("output") or "{}")
    if not isinstance(result, dict) or not isinstance(result.get("items"), list):
        raise LatchError("gmail search returned no items")
    degraded = [f"{d.get('account', '?')}: {d.get('error') or d.get('reason') or 'unavailable'}"
                for d in result.get("degraded") or [] if isinstance(d, dict)]
    seen, candidates = {}, []
    for row in result["items"]:
        if not isinstance(row, dict) or not row.get("id") or not row.get("date"):
            continue
        key = f"{row.get('account', '')}:{row['id']}"
        seen[key] = row["date"]
        if cursor.get(key) == row["date"]:
            continue
        reason = email_drop_reason(row)
        if reason:
            _count(dropped, "email", reason)
            continue
        candidates.append({
            "source": "email", "from_name": _name(row.get("from", "")), "chat_or_thread_id": row["id"],
            "text": str(row.get("subject") or "").strip(), "received_at": _stamp(_utc(row["date"])),
            "item": f"gmail:{key}@{row['date']}",
        })
    return candidates, seen, degraded


def read_imessage(call_tool, cursor, now, dropped):
    """(candidates, highest rowid seen)."""
    result = finish_command(call_tool, call_tool("plow_run_command", {
        "argv": IMESSAGE_ARGV, "read_paths": ["~/Library/Messages"], "goal": IMESSAGE_GOAL,
    }), "plow-messages search")
    code = int(result.get("exit_code", 1))
    if code != 0:
        raise LatchError(f"the Messages store could not be read (exit {code})")
    after = cursor.get("rowid") if isinstance(cursor, dict) else None
    floor = now - FIRST_LOOKBACK
    highest, candidates = after or 0, []
    for line in str(result.get("output") or "").splitlines():
        try:
            row = json.loads(line)
            rowid = int(row["rowid"])
            received = _utc(row["at"])
        except (ValueError, KeyError, TypeError):
            continue
        highest = max(highest, rowid)
        if (after is not None and rowid <= after) or (after is None and received < floor):
            continue
        reason = imessage_drop_reason(row)
        if reason:
            _count(dropped, "imessage", reason)
            continue
        candidates.append({
            "source": "imessage", "from_name": str(row.get("sender") or ""),
            "chat_or_thread_id": str(row.get("chat_guid") or row.get("chat_identifier") or ""),
            "text": str(row.get("body") or "").strip(), "received_at": _stamp(received),
            "item": f"imessage:{rowid}",
        })
    return candidates, highest


def scan(call_tool, now):
    sources = enabled_sources()
    cursor = _read_json(signals_dir() / ".cursor.json", {})
    pending = dict(cursor)
    candidates, dropped, degraded = [], {}, []
    if "email" in sources:
        try:
            found, seen, down = read_email(call_tool, cursor.get("email") or {}, dropped)
            candidates += found
            pending["email"] = seen
            degraded += [f"email: {d}" for d in down]
        except LatchError as error:
            degraded.append(f"email: {error}")
    if "imessage" in sources:
        try:
            found, highest = read_imessage(call_tool, cursor.get("imessage") or {}, now, dropped)
            candidates += found
            pending["imessage"] = {"rowid": highest}
        except LatchError as error:
            degraded.append(f"imessage: {error}")
    candidates.sort(key=lambda c: (c["received_at"], c["item"]), reverse=True)
    for extra in candidates[MAX_CANDIDATES:]:
        _count(dropped, extra["source"], "over-cap")
    if sources:
        _write_json(signals_dir() / ".pending.json", pending)
    return {"candidates": candidates[:MAX_CANDIDATES], "dropped": dropped, "degraded": degraded}


def commit():
    pending = signals_dir() / ".pending.json"
    if not pending.exists():
        return "CURSOR:unchanged"
    _write_json(signals_dir() / ".cursor.json", _read_json(pending, {}))
    pending.unlink()
    return "CURSOR:committed"


def main(argv=None, call_tool=None, now=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["scan", "commit"])
    try:
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    except SystemExit:
        return 2
    if args.command == "commit":
        print(commit())
        return 0
    if call_tool is None:
        from latch_mcp import connect
        try:
            call_tool = connect().call_tool
        except LatchError as error:
            sources = sorted(enabled_sources())
            print(json.dumps({"candidates": [], "dropped": {}, "degraded": [f"{s}: {error}" for s in sources]}))
            return 0
    print(json.dumps(scan(call_tool, now or datetime.now(timezone.utc)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
