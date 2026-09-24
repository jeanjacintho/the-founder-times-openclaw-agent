"""post_to_chat.py -- PDF-only payload vs text fallback."""
from __future__ import annotations

import json
import types
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from conftest import ROOT, load_module

sys.path.insert(0, str(ROOT / "pt-shared" / "scripts"))
post = load_module("post_to_chat", "pt-shared/scripts/post_to_chat.py")

MORNING = datetime(2026, 9, 19, 6, 4, tzinfo=ZoneInfo("America/Sao_Paulo"))
AFTERNOON = datetime(2026, 9, 19, 14, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))



def owner_zone(monkeypatch, tmp_path, tz):
    """--hold-until reads owner.timezone from PT_HOME's config.json."""
    home = tmp_path / "pt-home"
    home.mkdir(exist_ok=True)
    (home / "config.json").write_text(json.dumps({"owner": {"timezone": tz}}))
    monkeypatch.setenv("PT_HOME", str(home))

class TestComposePayload:
    @pytest.mark.parametrize("text", ["Mail summary", ""])
    def test_pdf_body_carries_the_optional_companion(self, text):
        assert post.compose_payload(text, "att_1") == {
            "body": text, "attachment_uids": ["att_1"],
        }

    def test_attachment_filename_defaults_to_basename(self):
        assert post.attachment_filename("/var/lib/plow/pt/run/edition.pdf") == (
            "edition.pdf"
        )

    def test_attachment_filename_override_is_a_paper_name_not_a_path(self):
        # Measured live: the chat showed the attachment as "edition.pdf"
        # because declare used the run-dir basename. The owner asked for
        # the newspaper, not a working-file name.
        assert (
            post.attachment_filename(
                "/var/lib/plow/pt/run/edition.pdf",
                "The-Founder-Times-2026-09-17.pdf",
            )
            == "The-Founder-Times-2026-09-17.pdf"
        )
        with pytest.raises(SystemExit, match="filename"):
            post.attachment_filename("edition.pdf", "../secret.pdf")

    def test_text_only_when_no_pdf(self):
        payload = post.compose_payload("THE FOUNDER TIMES")
        assert payload == {"body": "THE FOUNDER TIMES"}

    def test_text_only_refuses_blank_stdin(self):
        with pytest.raises(SystemExit, match="no edition text"):
            post.compose_payload("")


class TestTextFileFlag:
    """`--text-file` exists so the text leg needs no shell redirect.

    Measured live: told to "pass the chat text on stdin" with no command
    shown, a run built `/bin/sh -c '... post_to_chat.py < .../edition.chat.txt'`
    -- a shell operator, which is exactly what SOUL.md's gate flags. The owner
    got an /approve prompt instead of their newspaper.
    """

    def test_reads_the_edition_text_from_a_file(self, tmp_path):
        f = tmp_path / "edition.chat.txt"
        f.write_text("THE FOUNDER TIMES\nfront page\n", encoding="utf-8")
        assert post.read_text_file(str(f)) == "THE FOUNDER TIMES\nfront page"

    def test_missing_file_is_refused_by_name(self, tmp_path):
        with pytest.raises(SystemExit, match="text-file"):
            post.read_text_file(str(tmp_path / "nope.txt"))

    def test_blank_file_is_refused(self, tmp_path):
        f = tmp_path / "empty.txt"
        f.write_text("   \n", encoding="utf-8")
        with pytest.raises(SystemExit, match="empty"):
            post.read_text_file(str(f))


def _exits(code, stderr="", stdout=""):
    return lambda *a, **k: types.SimpleNamespace(returncode=code, stdout=stdout, stderr=stderr)


def _hangs(*a, **k):
    raise subprocess.TimeoutExpired(cmd="print_edition.py", timeout=k["timeout"])


class TestMissedPrintIsReported:
    """Measured 2026-09-22: a configured printer, a rendered PDF, no page and
    no word to the owner. Every miss now posts one line after the edition."""

    def _main(self, tmp_path, monkeypatch, argv, run=None, configured=True, language="English"):
        (tmp_path / "edition.json").write_text('{"date": "2026-09-22"}', encoding="utf-8")
        (tmp_path / "edition.chat.txt").write_text("THE FOUNDER TIMES", encoding="utf-8")
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"owner": {"language": language},
                                   "printer": {"configured": configured, "name": "JV"}}),
                       encoding="utf-8")
        monkeypatch.setattr(post, "CONFIG_DEFAULT", str(cfg))
        monkeypatch.setenv("PLOW_MCP_URL", "https://relay.invalid/mcp")
        monkeypatch.setenv("PLOW_AGENT_TOKEN", "tok")
        monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))
        monkeypatch.setattr(post, "resolve_chat", lambda: ("https://api.example", "cht_1", "tok"))
        monkeypatch.setattr(post, "declare_and_upload", lambda *a, **k: "att_1")
        monkeypatch.setattr(post, "run_finalize_topics", lambda *a: "FINALIZED")
        monkeypatch.setattr(post, "run_record_edition", lambda *a: "RECORDED")
        if run:
            monkeypatch.setattr(subprocess, "run", run)
        bodies = []
        monkeypatch.setattr(post, "post_json", lambda *a: bodies.append(a[-1]["body"]))
        monkeypatch.setattr(sys, "argv", ["post_to_chat.py", *[
            str(tmp_path / x) if x.startswith("edition") else x for x in argv]])
        post.main()
        return bodies[1:]

    @pytest.mark.parametrize("run, notice", [
        (_exits(0, stdout="page printed on JV"), []),
        (_exits(0, stdout="skipped: printer.configured is not true"), []),
        (_exits(1, "error: lp 1: no such printer"),
         ["page not printed — lp 1: no such printer; next scheduled run retries"]),
        (_exits(1, "warning: first\nerror: Mac unreachable"),
         ["page not printed — Mac unreachable; next scheduled run retries"]),
        (_exits(1, "error: lp outcome unknown: still running"),
         ["page not printed — lp outcome unknown: still running"]),
        (_exits(1), ["page not printed — exit 1; next scheduled run retries"]),
        (_hangs, [f"page not printed — outcome unknown: still running after {post.PRINT_TIMEOUT}s"]),
    ])
    def test_pdf_leg_posts_one_line_only_for_a_missed_page(self, tmp_path, monkeypatch, run, notice):
        (tmp_path / "edition.pdf").write_bytes(b"%PDF")
        assert self._main(tmp_path, monkeypatch, ["--pdf", "edition.pdf"], run) == notice

    @pytest.mark.parametrize("configured, language, notice", [
        (True, "English",
         ["page not printed — no PDF to print at {pdf}; next scheduled run retries"]),
        (True, "Português",
         ["página não impressa — nenhum PDF para imprimir em {pdf}; "
          "a próxima edição agendada tenta de novo"]),
        (False, "English", []),
    ])
    def test_text_fallback_says_why_the_configured_printer_got_nothing(
            self, tmp_path, monkeypatch, configured, language, notice):
        # Real print_edition.py: the text leg runs when no PDF was rendered.
        out = self._main(tmp_path, monkeypatch, ["--text-file", "edition.chat.txt"],
                         configured=configured, language=language)
        assert out == [n.format(pdf=tmp_path / "edition.pdf") for n in notice]


class TestRunRecord:
    """post_to_chat.py records the edition itself now, the same way it prints."""

    def test_a_hung_recorder_times_out_instead_of_blocking_the_run(self, monkeypatch):
        def fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="record_edition.py", timeout=kwargs.get("timeout"))

        monkeypatch.setattr(subprocess, "run", fake_run)
        out = post.run_record_edition("run/1/edition.json", MORNING)
        assert out == f"edition not recorded — timed out after {post.RECORD_TIMEOUT}s"

    def test_passes_the_delivered_at_it_was_given_as_the_now_flag(self, monkeypatch):
        # issue #48: this must be the timestamp captured right before the
        # chat POST, not a fresh clock read taken here after other
        # finalizers run.
        argv = []
        monkeypatch.setattr(subprocess, "run", lambda a, **k: argv.extend(a) or
                             types.SimpleNamespace(returncode=0, stdout="RECORDED x.md", stderr=""))
        post.run_record_edition("run/1/edition.json", MORNING)
        assert argv[-2:] == ["--now", MORNING.isoformat()]


class TestFinalizersRunIndependently:
    """The paper comes before the archive, and no finalizer's failure blocks
    another's: finalize, print and record each run best-effort, in order."""

    def _mock_main(self, tmp_path, monkeypatch, pdf_arg=None, **overrides):
        pdf = tmp_path / "edition.pdf"
        pdf.write_bytes(b"%PDF")
        monkeypatch.setenv("PT_HOME", str(tmp_path / "pt"))
        monkeypatch.setattr(post, "resolve_chat", lambda: ("https://api.example", "cht_1", "tok"))
        monkeypatch.setattr(post, "read_message", lambda: "")
        monkeypatch.setattr(post, "declare_and_upload", lambda *a, **k: "att_1")
        monkeypatch.setattr(post, "post_json", lambda *a, **k: None)
        monkeypatch.setattr(
            post, "run_finalize_topics",
            overrides.get("run_finalize_topics", lambda *a, **k: "FINALIZED"),
        )
        if "print_page" in overrides:
            monkeypatch.setattr(post, "print_page", overrides["print_page"])
        if "run_record_edition" in overrides:
            monkeypatch.setattr(post, "run_record_edition", overrides["run_record_edition"])
        monkeypatch.setattr(sys, "argv", ["post_to_chat.py", "--pdf", pdf_arg or str(pdf)])

    @pytest.mark.parametrize("topics, print_result, recorded, error", [
        ("FINALIZED", None, "RECORDED", None),
        ("FINALIZED", "page not printed — lp 1", "RECORDED", None),
        ("topics not finalized — broken", None, "RECORDED",
         r"topics.py finalize-edition <edition.json>.*do not repost"),
        ("FINALIZED", None, "error: edition not recorded — broken",
         r"record_edition.py <edition.json> --now \S+.*do not repost"),
        ("topics not finalized — broken", None,
         "error: edition not recorded — broken",
         r"topics.py finalize-edition <edition.json>.*record_edition.py <edition.json> --now \S+.*do not repost"),
    ])
    def test_finalizers_continue_in_order(self, tmp_path, monkeypatch,
                                          topics, print_result, recorded, error):
        order = []
        paths = []
        self._mock_main(
            tmp_path, monkeypatch,
            run_finalize_topics=lambda path: paths.append(path) or order.append("finalize") or topics,
            print_page=lambda *a, **k: order.append("print") or print_result,
            run_record_edition=lambda path, delivered_at: paths.append(path) or order.append("record") or recorded,
        )
        if error:
            with pytest.raises(SystemExit, match=error):
                post.main()
        else:
            post.main()
        assert order == ["finalize", "print", "record"]
        expected = str(tmp_path / "edition.json")
        assert paths == [expected, expected]

    def test_a_print_failure_before_its_own_runner_still_records(self, tmp_path, monkeypatch):
        # print_page is real here: a pdf path subprocess cannot pass must
        # still cost only the page, never the record.
        order = []
        self._mock_main(
            tmp_path, monkeypatch, pdf_arg="bad\x00path",
            run_record_edition=lambda *a, **k: order.append("record") or "RECORDED",
        )
        post.main()
        assert order == ["record"]

    def test_record_gets_the_post_moment_not_a_clock_read_after_the_slow_print_step(
            self, tmp_path, monkeypatch):
        # issue #48: the print step can poll for minutes; record_edition.py's
        # own now must not be sampled after it, or a fast-printing edition
        # could out-race an already-recorded one that posted first but
        # printed slower.
        clock = iter([MORNING, AFTERNOON])  # captured at POST, then print "later"
        monkeypatch.setattr(post, "owner_now", lambda: next(clock))
        seen = []

        def fake_print_page(*a, **k):
            post.owner_now()  # simulates the slow print step's own clock read
            return "page printed"

        self._mock_main(
            tmp_path, monkeypatch,
            print_page=fake_print_page,
            run_record_edition=lambda path, at: seen.append(at) or "RECORDED",
        )
        post.main()
        assert seen == [MORNING]

    def test_delivery_has_no_duplicate_path_adapters(self):
        assert not hasattr(post, "maybe_finalize_topics")
        assert not hasattr(post, "maybe_record")

    def test_a_bad_owner_timezone_fails_before_the_message_is_sent(self, tmp_path, monkeypatch):
        # srosro-review on 3eb4305: owner_now() can raise on a
        # configured-but-invalid owner.timezone. Raising AFTER post_json()
        # already delivered the message would skip every finalizer and
        # recovery command while the edition was still sent -- a retry
        # could then duplicate it. The clock read has to happen first.
        sent = []
        self._mock_main(tmp_path, monkeypatch)
        monkeypatch.setattr(post, "post_json", lambda *a, **k: sent.append(1))

        def bad_clock():
            raise KeyError("bad-zone")

        monkeypatch.setattr(post, "owner_now", bad_clock)
        with pytest.raises(KeyError):
            post.main()
        assert sent == []


class TestHoldUntil:
    """Scheduled papers start early; chat must wait for delivery.hour.

    Measured live: lead_minutes alone started research at hour−lead, then
    post_to_chat sent the PDF the moment the recipe finished — not at the
    hour the owner named. --hold-until is the send clock. If that hour has
    already passed, send now; never sleep until tomorrow.
    """

    @pytest.mark.parametrize("tz, now, hour, expected", [
        ("America/Sao_Paulo", datetime(2026, 9, 20, 6, 20), "07:00", 40 * 60),
        # 2026-11-01 01:30 in New York is EDT and 02:00 is EST, so the wall
        # clock spans 30 minutes but the hold is 2.5 real hours.
        ("America/New_York", datetime(2026, 11, 1, 1, 30), "03:00", 2.5 * 3600),
        ("UTC", datetime(2026, 9, 20, 7, 1), "07:00", 0),  # past: now, never tomorrow
    ])
    def test_seconds_until_hour(self, monkeypatch, tmp_path, tz, now, hour, expected):
        owner_zone(monkeypatch, tmp_path, tz)
        assert post.seconds_until_hhmm(hour, now=now.replace(tzinfo=ZoneInfo(tz))) == expected

    @pytest.mark.parametrize("now, expected", [
        (datetime(2026, 9, 20, 6, 59, 30), [30]),
        (datetime(2026, 9, 20, 8, 0, 0), []),  # already due: no sleep
    ])
    def test_hold_sleeps_only_the_remaining_seconds(self, monkeypatch, tmp_path, now, expected):
        owner_zone(monkeypatch, tmp_path, "UTC")
        slept = []
        post.hold_until("07:00", sleep=slept.append, now=now.replace(tzinfo=ZoneInfo("UTC")))
        assert slept == expected

    def test_the_owner_zone_wins_over_the_container_tz(self, monkeypatch, tmp_path):
        owner_zone(monkeypatch, tmp_path, "America/Sao_Paulo")
        monkeypatch.setenv("TZ", "Asia/Tokyo")
        now = datetime(2026, 9, 20, 6, 20, tzinfo=ZoneInfo("America/Sao_Paulo"))
        assert post.seconds_until_hhmm("07:00", now=now) == 40 * 60

    def test_bad_clock_is_refused(self):
        with pytest.raises(SystemExit, match="hold-until"):
            post.seconds_until_hhmm("7:00")


class TestPrintMissInTheOwnersLanguage:
    """owner.language is free-form: a language with no curated lines speaks
    through the phrases the paper wrote for it, and English until it has."""

    ZH = {"print.lede": "页面未打印 — ", "print.retry": "；下一次定时运行会重试",
          "print.timeout": "结果未知：{seconds}秒后仍在运行", "print.no_pdf": "{path} 没有可打印的 PDF"}

    def _write_phrases(self, tmp_path, language):
        phrases = load_module("owner_phrases", "pt-shared/scripts/owner_phrases.py")
        table = {**{k: "ZH " + v for k, v in phrases.SOURCE.items()}, **self.ZH}
        home = tmp_path / "pt"
        home.mkdir(exist_ok=True)
        (home / "owner-phrases.json").write_text(json.dumps({"language": language, "phrases": table}, ensure_ascii=False))

    def _miss(self, tmp_path, monkeypatch):
        (tmp_path / "edition.pdf").write_bytes(b"%PDF")
        return TestMissedPrintIsReported()._main(tmp_path, monkeypatch, ["--pdf", "edition.pdf"],
                                                 _exits(1, "error: lp 1: no such printer"), language="Mandarin Chinese")

    def test_a_written_language_gets_its_own_line(self, tmp_path, monkeypatch):
        self._write_phrases(tmp_path, "Mandarin Chinese")
        assert self._miss(tmp_path, monkeypatch) == ["页面未打印 — lp 1: no such printer；下一次定时运行会重试"]

    def test_phrases_for_another_language_are_never_used(self, tmp_path, monkeypatch):
        self._write_phrases(tmp_path, "Deutsch")
        assert self._miss(tmp_path, monkeypatch) == ["page not printed — lp 1: no such printer; next scheduled run retries"]
