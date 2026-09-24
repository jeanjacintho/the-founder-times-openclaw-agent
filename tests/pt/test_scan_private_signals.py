"""scan_private_signals.py -- mail and iMessage candidates, behind a spam filter."""
from __future__ import annotations

import contextlib
import io
import json
from datetime import datetime, timezone

import pytest

from conftest import load_module
from latch_mcp import LatchError

scan = load_module("scan_private_signals", "pt-priority/scripts/scan_private_signals.py")

NOW = datetime(2026, 9, 24, 13, 0, tzinfo=timezone.utc)


@pytest.fixture
def pt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    return tmp_path


def enable(pt_home, **sources):
    (pt_home / "config.json").write_text(json.dumps(
        {"signals": {"group_chat": False, "email": False, "imessage": False, **sources}}))


def gmail(*rows, degraded=()):
    return {"degraded": list(degraded), "items": list(rows), "status": "completed"}


def mail(id, sender, subject, date="2026-09-24 11:00", account="me@x.com"):
    return {"account": account, "date": date, "from": sender, "id": id, "subject": subject,
            "externalContent": {"source": "google_api", "untrusted": True, "wrapped": True}}


def messages(*rows, exit_code=0):
    return {"exit_code": exit_code, "output": "\n".join(json.dumps(r) for r in rows), "status": "completed"}


def text(rowid, sender, body, at="2026-09-24T09:30:00-03:00", is_from_me=0, chat="iMessage;-;+5511988887777"):
    return {"rowid": rowid, "chat_guid": chat, "chat_identifier": sender, "display_name": "",
            "sender": sender, "is_from_me": is_from_me, "at": at, "body": body}


class FakeLatch:
    def __init__(self, mail_result=None, messages_result=None):
        self.results = {"plow-gog": mail_result or gmail(), "plow-messages": messages_result or messages()}
        self.calls = []

    def call_tool(self, name, args):
        assert name == "plow_run_command", name
        self.calls.append(args)
        result = self.results[args["argv"][0]]
        if isinstance(result, Exception):
            raise result
        return result


def run(latch, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = scan.main(list(argv), call_tool=latch.call_tool, now=NOW)
    return code, buf.getvalue().strip()


@pytest.mark.parametrize("sender, reason", [
    ("Newsletter <noreply@substack.com>", "automated-sender"),
    ("GitHub <notifications@github.com>", "automated-sender"),
    ("MAILER-DAEMON@x.com", "automated-sender"),
    ("Loja <no-reply@loja.com.br>", "automated-sender"),
    ("Banco <naoresponda@banco.com.br>", "automated-sender"),
    ("Maya <maya@acme.com>", None),
    ("maya@acme.com", None),
])
def test_email_filter(sender, reason):
    assert scan.email_drop_reason(mail("t1", sender, "Renovação Acme")) == reason


@pytest.mark.parametrize("row, reason", [
    (text(1, "+5511999999999", "oi", is_from_me=1), "from-owner"),
    (text(2, "28273", "Promo imperdível!"), "short-code"),
    (text(3, "+5511988887777", "Seu código de verificação é 482913"), "verification-code"),
    (text(4, "+5511988887777", "Your login code: 1234"), "verification-code"),
    (text(5, "+5511988887777", "   "), "empty"),
    (text(6, "urn:biz:abc", "Pedido enviado"), "business"),
    (text(7, "+5511988887777", "Consegue ver o contrato hoje?"), None),
    (text(8, "maya@acme.com", "A Acme quer renovar"), None),
])
def test_imessage_filter(row, reason):
    assert scan.imessage_drop_reason(row) == reason


def test_spam_never_becomes_a_candidate(pt_home):
    enable(pt_home, email=True, imessage=True)
    latch = FakeLatch(
        gmail(mail("t1", "Newsletter <noreply@substack.com>", "Weekly"),
              mail("t2", "GitHub <notifications@github.com>", "PR"),
              mail("t3", "Maya <maya@acme.com>", "Renovação Acme")),
        messages(text(1, "28273", "Promo"), text(2, "+5511988887777", "Seu código é 482913"),
                 text(3, "+5511977776666", "Consegue ver o contrato hoje?")))
    code, out = run(latch, "scan")
    result = json.loads(out)
    assert code == 0 and result["degraded"] == []
    assert [c["text"] for c in result["candidates"]] == ["Consegue ver o contrato hoje?", "Renovação Acme"]
    assert result["dropped"] == {"email": {"automated-sender": 2}, "imessage": {"short-code": 1, "verification-code": 1}}


def test_candidates_carry_the_signal_contract_minus_category(pt_home):
    enable(pt_home, email=True, imessage=True)
    latch = FakeLatch(gmail(mail("t3", "Maya <maya@acme.com>", "Renovação Acme", date="2026-09-24 11:00")),
                      messages(text(3, "+5511977776666", "Contrato?", at="2026-09-24T09:30:00-03:00")))
    candidates = json.loads(run(latch, "scan")[1])["candidates"]
    assert candidates == [
        {"source": "imessage", "from_name": "+5511977776666", "chat_or_thread_id": "iMessage;-;+5511988887777",
         "text": "Contrato?", "received_at": "2026-09-24T12:30:00Z", "item": "imessage:3"},
        {"source": "email", "from_name": "Maya", "chat_or_thread_id": "t3",
         "text": "Renovação Acme", "received_at": "2026-09-24T11:00:00Z", "item": "gmail:me@x.com:t3@2026-09-24 11:00"},
    ]


def test_disabled_sources_make_no_latch_call(pt_home):
    enable(pt_home, group_chat=True)
    latch = FakeLatch()
    code, out = run(latch, "scan")
    assert code == 0 and json.loads(out) == {"candidates": [], "dropped": {}, "degraded": []}
    assert latch.calls == []


def test_argv_is_stable_between_runs(pt_home):
    enable(pt_home, email=True, imessage=True)
    first = FakeLatch(gmail(mail("t1", "Maya <maya@acme.com>", "A")), messages(text(5, "+5511977776666", "B")))
    run(first, "scan")
    run(first, "commit")
    second = FakeLatch(gmail(mail("t2", "Maya <maya@acme.com>", "C")), messages(text(9, "+5511977776666", "D")))
    run(second, "scan")
    assert first.calls[:2] == second.calls
    assert first.calls[0]["argv"] == ["plow-gog", "gmail", "search", scan.GMAIL_QUERY, "--max", "25", "--timezone", "UTC", "--json", "--fields", "id,date,from,subject"]
    assert second.calls[1] == {"argv": ["plow-messages", "search", "--limit", "200", "--order", "desc"],
                               "read_paths": ["~/Library/Messages"], "goal": scan.IMESSAGE_GOAL}


def test_cursor_moves_only_on_commit(pt_home):
    enable(pt_home, email=True, imessage=True)
    latch = FakeLatch(gmail(mail("t1", "Maya <maya@acme.com>", "A")), messages(text(5, "+5511977776666", "B")))
    assert len(json.loads(run(latch, "scan")[1])["candidates"]) == 2
    assert len(json.loads(run(latch, "scan")[1])["candidates"]) == 2, "no commit, same window"
    assert run(latch, "commit") == (0, "CURSOR:committed")
    assert json.loads(run(latch, "scan")[1])["candidates"] == [], "committed rows are not offered again"
    assert run(FakeLatch(), "commit") == (0, "CURSOR:committed")


def test_commit_without_a_scan_changes_nothing(pt_home):
    enable(pt_home, email=True)
    assert run(FakeLatch(), "commit") == (0, "CURSOR:unchanged")


def test_a_new_reply_in_a_seen_thread_is_offered_again(pt_home):
    enable(pt_home, email=True)
    run(FakeLatch(gmail(mail("t1", "Maya <maya@acme.com>", "A", date="2026-09-24 10:00"))), "scan")
    run(FakeLatch(), "commit")
    later = FakeLatch(gmail(mail("t1", "Maya <maya@acme.com>", "A", date="2026-09-24 12:00")))
    [candidate] = json.loads(run(later, "scan")[1])["candidates"]
    assert candidate["item"] == "gmail:me@x.com:t1@2026-09-24 12:00"


def test_first_imessage_scan_looks_back_two_days_only(pt_home):
    enable(pt_home, imessage=True)
    latch = FakeLatch(messages_result=messages(text(9, "+5511977776666", "new", at="2026-09-24T09:00:00-03:00"),
                                               text(2, "+5511977776666", "old", at="2026-09-10T09:00:00-03:00")))
    assert [c["text"] for c in json.loads(run(latch, "scan")[1])["candidates"]] == ["new"]


def test_candidates_are_capped_newest_first(pt_home):
    enable(pt_home, imessage=True)
    rows = [text(i, "+5511977776666", f"m{i}", at=f"2026-09-24T{i // 60:02d}:{i % 60:02d}:00+00:00") for i in range(1, 51)]
    result = json.loads(run(FakeLatch(messages_result=messages(*rows)), "scan")[1])
    assert len(result["candidates"]) == scan.MAX_CANDIDATES
    assert result["candidates"][0]["text"] == "m50"
    assert result["dropped"]["imessage"]["over-cap"] == 50 - scan.MAX_CANDIDATES


def test_rescan_after_a_crash_does_not_duplicate_a_signal(pt_home):
    enable(pt_home, imessage=True)
    intake = load_module("signal_intake", "pt-shared/scripts/signal_intake.py")
    latch = FakeLatch(messages_result=messages(text(5, "+5511977776666", "Contrato até sexta?")))
    for _ in range(2):  # the run dies after intake, before commit, and runs again
        [candidate] = json.loads(run(latch, "scan")[1])["candidates"]
        code, _ = intake.intake(json.dumps({**candidate, "category": "priority"}))
        assert code == 0
    assert len(list((pt_home / "signals").glob("imessage-*.json"))) == 1


@pytest.mark.parametrize("failure, expected", [
    (LatchError("latch blocked: Grant Full Disk Access to Latch"), "imessage: latch blocked: Grant Full Disk Access to Latch"),
    (LatchError("Mac unreachable"), "imessage: Mac unreachable"),
    (messages(exit_code=1), "imessage: the Messages store could not be read (exit 1)"),
])
def test_unreadable_imessage_is_degraded_never_empty(pt_home, failure, expected):
    enable(pt_home, email=True, imessage=True)
    latch = FakeLatch(gmail(mail("t3", "Maya <maya@acme.com>", "Renovação Acme")), failure)
    code, out = run(latch, "scan")
    result = json.loads(out)
    assert code == 0
    assert result["degraded"] == [expected]
    assert [c["source"] for c in result["candidates"]] == ["email"], "the other source still works"


def test_gmail_degraded_accounts_are_reported(pt_home):
    enable(pt_home, email=True)
    latch = FakeLatch(gmail(mail("t3", "Maya <maya@acme.com>", "Oi"), degraded=[{"account": "work@x.com", "error": "token expired"}]))
    result = json.loads(run(latch, "scan")[1])
    assert result["degraded"] == ["email: work@x.com: token expired"]
    assert len(result["candidates"]) == 1


def test_a_failed_source_keeps_its_cursor(pt_home):
    enable(pt_home, imessage=True)
    run(FakeLatch(messages_result=messages(text(5, "+5511977776666", "B"))), "scan")
    run(FakeLatch(), "commit")
    run(FakeLatch(messages_result=LatchError("Mac unreachable")), "scan")
    run(FakeLatch(), "commit")
    again = FakeLatch(messages_result=messages(text(6, "+5511977776666", "C"), text(5, "+5511977776666", "B")))
    assert [c["item"] for c in json.loads(run(again, "scan")[1])["candidates"]] == ["imessage:6"]


def test_bad_usage_is_exit_2(pt_home):
    assert run(FakeLatch(), "nope")[0] == 2
