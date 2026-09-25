#!/usr/bin/env python3
"""post_to_chat.py -- the edition's chat leg: POST the PDF (or, if none, the
chat text) to the owner's home channel over the Plow Chat API, directly,
with no dependency on a connected live platform adapter.

Originally the fallback for a run with no --deliver arm. Promoted to the
PRIMARY chat leg (not a fallback) after measuring cron/scheduler.py's own
delivery live: the same unchanged content, run to run, both delivered fine
via --deliver and was silently discarded with "Fire claim ownership lost;
stale result was discarded" -- a genuine intermittent race in the previous
runtime's cron heartbeat/claim mechanism, not anything about this script's content.
Calling the Plow Chat REST API directly, the same three calls
plow-chat-platform's own adapter makes internally (declare an attachment,
PUT the bytes to its signed upload_url, POST the message with
attachment_uids), needs no live adapter and is not subject to that race --
it is a plain HTTP call that either succeeds or exits loudly, same as the
text-only POST below always was.

Text is read from ``--text-file`` when provided, otherwise from STDIN only
when there is no PDF. With ``--pdf``, ``--text-file`` is reserved for the
small mail/sports companion omitted from the printed page; without it the
message is attachment-only. The full chat transcript is never a caption.
Omit ``--pdf`` to post text only (the fallback when weasyprint could not
write the file).

The endpoint and credential come
from the process environment alone (PLOW_API_BASE, PLOW_HOME_CHANNEL,
PLOW_AGENT_TOKEN), which first boot publishes from the credential the host
dropped in: a file the agent can write is not a place to look for the API
base its own bearer is sent to. Any of the three unset or blank is refused
BY NAME, before anything posts, so a half-delivered run cannot happen.

`--pdf PATH` attaches that file (declare -> upload -> message-with-
attachment_uids) and optionally sends the companion as its body.
`--hold-until HH:MM` is a scheduled paper's send clock, on the owner's
clock. If that hour has passed it posts now. If it is still ahead, nothing
waits in the session (OpenClaw's exec is synchronous with a 30-minute
ceiling, and a paper starts up to 150 minutes early): the PDF, companion or
text, `edition.json` and each news section's notes are copied into
`pt/outbox/<date>-<HHMM>/` with a `delivery.json`, it prints `held for HH:MM
— pt-deliver posts it` and exits 0. The no-agent `pt-deliver` job runs
`post_to_chat.py --flush-outbox` every minute and posts each entry once its
hour has come, through the same delivery as the direct path. Without a
registered, enabled `pt-deliver` the paper posts now -- early, never stranded.
`delivery.json` is removed the moment the POST returns, so nothing posts
twice; a finalizer failure keeps the entry for its recovery command.
After a successful POST, three
finalizers run independently and best-effort: finalize exactly the topics carried by
`edition.json`, print the run's PDF via print_edition.py when configured (a
miss posts one line saying why), and record via
record_edition.py (`--pdf` and `--text-file` both) on the sibling
`edition.json` -- one's failure never skips or undoes another, and nothing
about the record reaches chat. `--dry-run` prints the redacted envelope and
never sends.
"""
from __future__ import annotations

import argparse
import fcntl
import mimetypes
import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from bearer_http import post_json, post_json_read, put_bytes, require
from owner_chat import home_channel
from owner_phrases import phrase
from owner_time import owner_now
from pt_paths import config_file, pt_home
from setup_needed import owner_language


CONFIG_DEFAULT = str(config_file())
PRINT_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "pt-print"
    / "scripts"
    / "print_edition.py"
)
RECORD_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "pt-edition"
    / "scripts"
    / "record_edition.py"
)
TOPICS_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "pt-intake"
    / "scripts"
    / "topics.py"
)


HOLD_UNTIL_RE = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


def _hold_zone():
    """The owner's zone: the scheduler fires jobs on owner.timezone (--tz), so
    the send clock is the same wall clock, never the container's TZ."""
    return owner_now().tzinfo


def seconds_until_hhmm(hhmm, now=None):
    """Seconds from now until today's HH:MM on the owner's clock; 0 if passed.

    Never wraps to tomorrow: a late paper posts immediately rather than
    sitting until the next day's hour.
    """
    if not isinstance(hhmm, str) or not HOLD_UNTIL_RE.fullmatch(hhmm):
        sys.exit(f"error: --hold-until is not HH:MM: {hhmm!r}")
    tz = _hold_zone()
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)
    hour, minute = map(int, hhmm.split(":"))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Absolute instants: same-zone datetime subtraction is wall-clock and
    # is an hour off across a DST change.
    remaining = target.timestamp() - now.timestamp()
    return max(0.0, remaining)


def _now():
    return datetime.now(_hold_zone())


DELIVER_JOB = "pt-deliver"
DASHBOARD_SCRIPTS = Path(__file__).resolve().parent.parent.parent / "pt-dashboard" / "scripts"


def outbox_dir():
    return pt_home() / "outbox"


def deliver_job_runs():
    """Whether the pt-deliver job is registered and enabled -- asked of the one
    reader of the scheduler (cron_backend). Any doubt is "no", so a paper
    posts early rather than waiting on a job that will never flush it."""
    sys.path.insert(0, str(DASHBOARD_SCRIPTS))
    try:
        from cron_backend import CronBackend
        return any(job.name == DELIVER_JOB and job.enabled for job in CronBackend().list())
    except (SystemExit, Exception):
        return False


def _notes_source(run_dir, topic_id):
    for candidate in (run_dir.parent / topic_id / "notes.json", run_dir / topic_id / "notes.json",
                      pt_home() / "run" / topic_id / "notes.json"):
        if candidate.is_file():
            return candidate
    return None


def stage(hhmm, due, pdf=None, text_file=None, text="", filename=None):
    """Copy this paper into the outbox for pt-deliver; the run's own files may
    be archived by the next paper before the hour comes."""
    name = f"{due:%Y-%m-%d}-{hhmm.replace(':', '')}"
    outbox = outbox_dir()
    outbox.mkdir(parents=True, exist_ok=True)
    building = outbox / f".{name}.{os.getpid()}"
    shutil.rmtree(building, ignore_errors=True)
    building.mkdir()
    posted = Path(pdf or text_file)
    delivery = {"due": due.isoformat(), "hold_until": hhmm, "pdf": None, "text_file": None,
                "text": None, "filename": None}
    if pdf:
        shutil.copyfile(pdf, building / "edition.pdf")
        delivery["pdf"] = "edition.pdf"
        delivery["filename"] = attachment_filename(pdf, filename)
    if text_file:
        shutil.copyfile(text_file, building / "edition.text.txt")
        delivery["text_file"] = "edition.text.txt"
    elif text:
        delivery["text"] = text
    edition_json = posted.parent / "edition.json"
    if edition_json.is_file():
        shutil.copyfile(edition_json, building / "edition.json")
        try:
            sections = json.loads(edition_json.read_text(encoding="utf-8")).get("sections") or []
        except (OSError, ValueError, AttributeError):
            sections = []
        for section in sections:
            topic_id = section.get("topic_id") if isinstance(section, dict) else None
            source = _notes_source(posted.parent, topic_id) if topic_id else None
            if source:
                (building / topic_id).mkdir(exist_ok=True)
                shutil.copyfile(source, building / topic_id / "notes.json")
    (building / "delivery.json").write_text(json.dumps(delivery, indent=2) + "\n", encoding="utf-8")
    final = outbox / name
    shutil.rmtree(final, ignore_errors=True)
    os.replace(building, final)
    return final


def resolve_chat():
    """The chat endpoint (base + path) + bearer, validated before anything posts."""
    base = require("PLOW_API_BASE").rstrip("/")
    uid = home_channel()
    token = require("PLOW_AGENT_TOKEN")
    return base, uid, token


def read_message():
    return sys.stdin.read().strip()


def read_text_file(path):
    """The edition text from a file, so the text leg needs no shell redirect.

    Measured live: told to "pass the chat text on stdin" with no command
    shown, a run built `/bin/sh -c '... post_to_chat.py < edition.chat.txt'`.
    A shell operator is exactly what SOUL.md's gate flags, so the owner got
    an /approve prompt instead of their newspaper. A flag needs no shell.
    """
    try:
        text = open(path, encoding="utf-8").read().strip()
    except OSError:
        sys.exit(f"error: --text-file path cannot be read: {path}")
    if not text:
        sys.exit(f"error: --text-file is empty: {path}")
    return text


def attachment_filename(pdf_path, override=None):
    """The name Plow Chat shows on the attachment.

    Measured live: declare used os.path.basename of the run-dir file, so
    the owner saw "edition.pdf" in the thread. An override is a single
    basename (no slash), and always ends in .pdf.
    """
    name = override if override else os.path.basename(pdf_path)
    name = name.strip()
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        sys.exit("error: --filename must be a basename, not a path")
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def _best_effort(run, args, failure):
    """One finalizer, run to completion, never raised: SystemExit or any other
    exception becomes a failure string, exactly like the runner's own.
    """
    try:
        out = run(*args)
    except SystemExit as exc:
        out = str(exc) if exc.args else failure
    except Exception as exc:
        out = f"{failure} — {exc}"
    return (out or "").strip() or f"{failure} — empty result"


PRINT_TIMEOUT = 600


def print_page(pdf_path):
    """Print the page; the owner's one chat line if it did not, else None.

    print_edition.py exits 0 when it printed or when printer.configured is
    not true (silence). Any other exit, a hang, or a crash owes the owner a
    line, since the turn ends in NO_REPLY. The exit status says it failed
    and the script's last line says why (issue #79: no phrase is both the
    owner's lede and the selector), kept untranslated as diagnostic detail;
    the words this repo authors follow the owner's language. Measured
    2026-09-22: an on-demand run with a configured printer printed nothing
    and said nothing.
    """
    import subprocess

    try:
        proc = subprocess.run(
            [sys.executable, str(PRINT_SCRIPT), pdf_path, CONFIG_DEFAULT],
            capture_output=True,
            text=True,
            timeout=PRINT_TIMEOUT,
        )
        blob = ((proc.stdout or "") + (proc.stderr or "")).strip()
        print(blob)
        if proc.returncode == 0:
            return None
        detail = blob.splitlines()[-1] if blob else f"exit {proc.returncode}"
    except subprocess.TimeoutExpired:
        detail = None
    except Exception as exc:
        detail = str(exc)
    # The print-miss words are owner_phrases.py's: the owner's own language
    # when the paper has written it, curated Portuguese or English otherwise.
    language = owner_language(CONFIG_DEFAULT)
    lede = phrase("print.lede", language)
    if detail is None:  # an unknown outcome may still print: no retry promise
        return lede + phrase("print.timeout", language, seconds=PRINT_TIMEOUT)
    if not os.path.isfile(pdf_path):
        detail = phrase("print.no_pdf", language, path=pdf_path)
    line = lede + detail.removeprefix("error: ")[:200]
    return line if "outcome unknown" in detail else line + phrase("print.retry", language)


RECORD_TIMEOUT = 300


def run_record_edition(edition_json, delivered_at):
    """delivered_at is captured once in main(), immediately before the chat
    POST, under the same delivery-order lock, and passed through -- not a
    fresh owner_now() here, well after whatever the print step's own
    polling took, which would otherwise stand in for this edition's own
    time and let it out-race an already-recorded one that posted later but
    printed faster (issue #48)."""
    import subprocess

    try:
        proc = subprocess.run(
            [sys.executable, str(RECORD_SCRIPT), edition_json,
             "--now", delivered_at.isoformat()],
            capture_output=True,
            text=True,
            timeout=RECORD_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return f"edition not recorded — timed out after {RECORD_TIMEOUT}s"
    blob = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        if "edition not recorded" in blob:
            return blob
        return f"edition not recorded — {blob or proc.returncode}"
    return blob


def run_finalize_topics(edition_json):
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(TOPICS_SCRIPT), "finalize-edition", edition_json],
        capture_output=True,
        text=True,
    )
    blob = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if proc.returncode != 0:
        return f"topics not finalized — {blob or proc.returncode}"
    return blob


def compose_payload(text, attachment_uid=None):
    """One chat message: PDF plus optional companion, or the chat edition.

    plow-chat-platform posts ``{"body": "", "attachment_uids": [...]}`` for
    attachment-only sends; an empty body with a PDF remains valid when there
    are no chat-only desks.
    """
    if attachment_uid:
        return {"body": text, "attachment_uids": [attachment_uid]}
    if not text:
        sys.exit("error: no edition text on stdin")
    return {"body": text}


def declare_and_upload(base, uid, token, pdf_path, filename=None):
    """Declare the attachment, PUT its bytes to the signed upload_url, return its uid.

    Mirrors plow-chat-platform's own ``_send_attachment`` exactly (same three
    calls, same field names) -- this is not a new contract, just this
    script's own copy of the one Plow's REST API defines.
    """
    if not os.path.isfile(pdf_path):
        sys.exit(f"error: --pdf path does not exist: {pdf_path}")
    with open(pdf_path, "rb") as fh:
        data = fh.read()
    filename = attachment_filename(pdf_path, filename)
    content_type = mimetypes.guess_type(filename)[0] or "application/pdf"
    declared = post_json_read(
        base, f"/v1/chats/{uid}/attachments", token, "Plow Chat attachment declare",
        {"filename": filename, "content_type": content_type, "size_bytes": len(data)},
    )
    put_bytes(declared["upload_url"], declared.get("upload_headers") or {}, data,
              "Plow Chat attachment")
    return declared["uid"]


def main():
    parser = argparse.ArgumentParser(description="Post an edition to the owner's Plow Chat.")
    parser.add_argument(
        "--pdf", default=None,
        help="path to a PDF to attach (declare -> upload -> attach, same call the "
             "platform's own adapter makes); omit to post text only",
    )
    parser.add_argument(
        "--text-file", default=None,
        help="read the chat edition, or a PDF's chat-only desk companion, "
             "from this file instead of stdin (no shell redirect needed)",
    )
    parser.add_argument(
        "--filename", default=None,
        help="attachment name shown in chat (basename). Default is the PDF's "
             "own basename, which for a run file is edition.pdf",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the request instead of sending it"
    )
    parser.add_argument(
        "--hold-until", default=None, metavar="HH:MM",
        help="the send clock (owner's HH:MM): stage the paper for pt-deliver while "
             "it is ahead, post now once it has passed (scheduled papers only)",
    )
    parser.add_argument(
        "--flush-outbox", action="store_true",
        help="post every staged paper whose hour has come (the pt-deliver job)",
    )
    args = parser.parse_args()
    if args.flush_outbox:
        sys.exit(main_flush())

    base, uid, token = resolve_chat()
    if args.text_file:
        text = read_text_file(args.text_file)
    elif args.pdf:
        text = ""
    else:
        text = read_message()
    if not args.pdf and not text:
        sys.exit("error: no edition text on stdin")

    if args.dry_run:
        attach_note = f" + attach {args.pdf}" if args.pdf else ""
        if args.pdf:
            attach_note += f" as {attachment_filename(args.pdf, args.filename)}"
        kind = (f"pdf + {len(text)} chars" if args.pdf and text else "pdf-only") \
            if args.pdf else f"{len(text)} chars"
        print(
            f"dry-run: would POST {kind} to {base}/v1/chats/{uid}/messages"
            f'{attach_note}'
        )
        return

    if args.hold_until:
        remaining = seconds_until_hhmm(args.hold_until, now=_now())
        if remaining > 0:
            if deliver_job_runs():
                due = _now() + timedelta(seconds=remaining)
                stage(args.hold_until, due, pdf=args.pdf, text_file=args.text_file,
                      text=text, filename=args.filename)
                print(f"held for {args.hold_until} — pt-deliver posts it")
                return
            print(f"{DELIVER_JOB} is not running: posting now instead of holding for {args.hold_until}")

    deliver(base, uid, token, pdf=args.pdf, text=text, filename=args.filename,
            text_file=args.text_file)


def deliver(base, uid, token, *, pdf=None, text="", filename=None, text_file=None, on_posted=None):
    """POST the edition, then the three finalizers. `on_posted` runs the moment
    the POST returns, before any finalizer (the outbox drops its delivery.json
    there, so a flush never posts twice)."""
    attachment_uid = None
    if pdf:
        attachment_uid = declare_and_upload(base, uid, token, pdf, filename=filename)
    body = compose_payload(text, attachment_uid)

    # Two concurrent runs (the daily job and an on-demand copy, say) can
    # commit their messages in one order but have their HTTP responses land
    # in the other -- owner_now() read right after each POST would then
    # stamp the later-sent message as the earlier one, corrupting priority
    # ordering (issue #48). Serializing the clock read together with the
    # POST under one lock keeps send order and stamp order the same. The
    # read comes FIRST, still inside the lock: owner_now() raises on a
    # configured-but-invalid owner.timezone, and that has to fail before the
    # message is actually sent, not after -- post_json() has already
    # delivered the edition by the time any later step, finalizer, or
    # recovery instruction could run, so a bad timezone caught only there
    # would report a generic failure with no "do not repost" and risk a
    # duplicate send on retry.
    lock_path = pt_home() / "run" / "delivery-order.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        delivered_at = owner_now()
        post_json(base, f"/v1/chats/{uid}/messages", token, "Plow Chat", body)
    if on_posted:
        on_posted()
    posted_path = pdf or text_file
    edition_json = str(Path(posted_path).parent / "edition.json") if posted_path else None
    topics_result = (
        _best_effort(run_finalize_topics, (edition_json,), "topics not finalized")
        if edition_json else "skipped: no posted file"
    )
    print(topics_result)
    if pdf:
        suffix = " + companion" if text else " only"
        print(f"chat edition posted (pdf{suffix}) {pdf}")
    else:
        print(f"chat edition posted ({len(text)} chars)")
    # The text leg prints its run's PDF too: absent, the owner hears why.
    pdf = pdf or (str(Path(text_file).parent / "edition.pdf") if text_file else None)
    line = print_page(pdf) if pdf else None
    if line:
        try:  # the edition already posted: exit 0 must keep meaning that
            post_json(base, f"/v1/chats/{uid}/messages", token, "Plow Chat", {"body": line})
        except SystemExit as exc:
            print(f"print-failure notice not posted: {exc}", file=sys.stderr)
    recorded = (
        _best_effort(run_record_edition, (edition_json, delivered_at), "edition not recorded")
        if edition_json else "skipped: no posted file"
    )
    print(recorded)
    recoveries = []
    if topics_result.startswith("topics not finalized"):
        recoveries.append("topics.py finalize-edition <edition.json>")
    if "edition not recorded" in recorded:
        recoveries.append(f"record_edition.py <edition.json> --now {delivered_at.isoformat()}")
    if recoveries:
        sys.exit(
            "error: post-delivery finalization failed; recover with "
            + "; ".join(recoveries)
            + "; do not repost"
        )


def main_flush():
    """Post every staged paper whose hour has come; 0 when nothing failed.

    One flush at a time (an exclusive lock taken without waiting: a flush
    already running owns the outbox, and the next minute's run picks up the
    rest). An entry with no delivery.json was posted and is waiting on its
    recovery command; it is never posted again."""
    outbox = outbox_dir()
    if not outbox.is_dir():
        return 0
    failed = False
    with open(outbox / ".flush.lock", "a") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0
        now = _now()
        for entry in sorted(p for p in outbox.iterdir() if p.is_dir() and not p.name.startswith(".")):
            ticket = entry / "delivery.json"
            try:
                delivery = json.loads(ticket.read_text(encoding="utf-8"))
                due = datetime.fromisoformat(delivery["due"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if due > now:
                continue
            text = read_text_file(str(entry / delivery["text_file"])) if delivery.get("text_file") else (delivery.get("text") or "")
            try:
                base, uid, token = resolve_chat()
                deliver(base, uid, token, pdf=str(entry / delivery["pdf"]) if delivery.get("pdf") else None,
                        text=text, filename=delivery.get("filename"),
                        text_file=str(entry / delivery["text_file"]) if delivery.get("text_file") else None,
                        on_posted=lambda: ticket.unlink(missing_ok=True))
            except SystemExit as exc:
                print(f"{entry.name}: {exc}", file=sys.stderr)
                failed = True
                continue
            shutil.rmtree(entry, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    main()
