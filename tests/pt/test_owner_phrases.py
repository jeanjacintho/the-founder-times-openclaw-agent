"""owner_phrases.py -- the fixed lines scripts and the channel write, in the owner's language."""
from __future__ import annotations

import contextlib
import io
import json

import pytest

from conftest import load_module

phrases = load_module("owner_phrases", "pt-shared/scripts/owner_phrases.py")


@pytest.fixture
def pt_home(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    return tmp_path


def configure(pt_home, language):
    (pt_home / "config.json").write_text(json.dumps({"owner": {"timezone": "UTC", "language": language}}))


def translated(prefix="ZH "):
    """A complete, well-formed translation: every key, every placeholder kept."""
    return {key: prefix + text for key, text in phrases.SOURCE.items()}


def run(argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), \
         contextlib.ExitStack() as stack:
        stack.enter_context(pytest.MonkeyPatch.context()).setattr("sys.stdin", io.StringIO(stdin))
        code = phrases.main(argv)
    return code, out.getvalue().strip(), err.getvalue().strip()


def test_the_closed_set_covers_every_fixed_line():
    assert set(phrases.SOURCE) == {
        "chat.busy", "chat.busy_still",
        "print.lede", "print.retry", "print.timeout", "print.no_pdf",
        "turn.failed",
        "page.first_step", "page.questions", "page.sources", "page.could_not_source",
        "page.nothing_to_report", "page.advice_from", "page.priority_band",
    }
    assert "{seconds}" in phrases.SOURCE["print.timeout"] and "{path}" in phrases.SOURCE["print.no_pdf"]


def test_template_prints_the_english_source(pt_home):
    configure(pt_home, "Mandarin Chinese")
    code, out, _ = run(["template"])
    assert code == 0
    assert json.loads(out) == {"language": "Mandarin Chinese", "phrases": phrases.SOURCE}


@pytest.mark.parametrize("language, status", [
    ("English", "ready"), ("en-US", "ready"), ("Português", "ready"), ("pt-BR", "ready"),
    ("Mandarin Chinese", "missing"), ("Deutsch", "missing"), ("", "missing"),
])
def test_status_without_a_file(pt_home, language, status):
    configure(pt_home, language)
    assert run(["status"])[1] == f"PHRASES:{status}"


def test_record_then_every_line_is_the_owners(pt_home):
    configure(pt_home, "Mandarin Chinese")
    code, out, err = run(["record"], json.dumps({"phrases": translated()}))
    assert (code, out, err) == (0, "PHRASES:ready", "")
    assert run(["status"])[1] == "PHRASES:ready"
    assert phrases.phrase("turn.failed") == "ZH " + phrases.SOURCE["turn.failed"]
    assert phrases.phrase("print.timeout", seconds=120) == "ZH " + phrases.SOURCE["print.timeout"].format(seconds=120)


def test_a_language_change_makes_the_file_stale(pt_home):
    configure(pt_home, "Mandarin Chinese")
    run(["record"], json.dumps({"phrases": translated()}))
    configure(pt_home, "Deutsch")
    assert run(["status"])[1] == "PHRASES:missing"
    assert phrases.phrase("turn.failed") == phrases.SOURCE["turn.failed"], "stale phrases never speak another language"


def test_without_a_file_portuguese_and_english_keep_their_curated_lines(pt_home):
    configure(pt_home, "Português")
    assert phrases.phrase("chat.busy") == "⏳ Um instante — tô nessa."
    configure(pt_home, "English")
    assert phrases.phrase("chat.busy") == "⏳ Hang on a sec — still setting up."
    configure(pt_home, "Mandarin Chinese")
    assert phrases.phrase("chat.busy") == "⏳ Hang on a sec — still setting up."


@pytest.mark.parametrize("broken, reason", [
    (lambda p: p.pop("turn.failed"), "missing: turn.failed"),
    (lambda p: p.update({"turn.failed": "  "}), "blank: turn.failed"),
    (lambda p: p.update({"print.timeout": "sem placeholder"}), "placeholders differ: print.timeout"),
    (lambda p: p.update({"print.no_pdf": "{path} {extra}"}), "placeholders differ: print.no_pdf"),
    (lambda p: p.update({"extra.key": "x"}), "unknown: extra.key"),
])
def test_a_malformed_translation_is_refused_and_nothing_is_written(pt_home, broken, reason):
    configure(pt_home, "Mandarin Chinese")
    table = translated()
    broken(table)
    code, out, err = run(["record"], json.dumps({"phrases": table}))
    assert code == 1 and out == "" and reason in err
    assert not (pt_home / "owner-phrases.json").exists()


def test_record_refuses_without_a_recorded_language(pt_home):
    configure(pt_home, "")
    code, _, err = run(["record"], json.dumps({"phrases": translated()}))
    assert code == 1 and "no owner.language" in err


def test_the_file_names_the_language_it_was_written_for(pt_home):
    configure(pt_home, "Mandarin Chinese")
    run(["record"], json.dumps({"phrases": translated()}))
    stored = json.loads((pt_home / "owner-phrases.json").read_text())
    assert stored["language"] == "Mandarin Chinese" and set(stored["phrases"]) == set(phrases.SOURCE)
