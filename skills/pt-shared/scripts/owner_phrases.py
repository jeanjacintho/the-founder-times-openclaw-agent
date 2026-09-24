#!/usr/bin/env python3
"""owner_phrases.py -- the paper's fixed lines, in the owner's language.

Scripts and the channel write a few lines no model is there to phrase: the
setup wait lines, the print-miss line, the failed-turn notice, the printed
page's labels. `owner.language` is free-form ("Mandarin in, Mandarin out"),
and no table in code can hold every language -- so the model writes the
closed set once, in the owner's language, and everything reads it here.

    owner_phrases.py template    the English source as JSON, to translate
    owner_phrases.py record      one translation as JSON on stdin -> $PT_HOME/owner-phrases.json
    owner_phrases.py status      PHRASES:ready | PHRASES:missing

`record` refuses (exit 1, `error: …`) a translation that misses or adds a key,
leaves one blank, or changes a `{placeholder}`; nothing is written then. The
file names the language it was written for, and is used only while that is
still `owner.language`: a language change makes it stale, and the lines fall
back to the curated English or Portuguese below. English and Portuguese are
`ready` with no file at all.

Library: `phrase(key, language=None, **fields)` -> the line, formatted.
"""
from __future__ import annotations

import json
import os
import string
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import setup_needed as _gate  # noqa: E402
from owner_language import is_portuguese  # noqa: E402
from pt_paths import config_file, pt_home  # noqa: E402

PRINT_TIMEOUT_NOTE = "outcome unknown: still running after {seconds}s"

# The English source: every key a translation must carry, with its placeholders.
SOURCE = {
    "chat.busy": "⏳ Hang on a sec — still setting up.",
    "chat.busy_still": "⏳ Still on it — back in a moment.",
    "print.lede": "page not printed — ",
    "print.retry": "; next scheduled run retries",
    "print.timeout": PRINT_TIMEOUT_NOTE,
    "print.no_pdf": "no PDF to print at {path}",
    "turn.failed": ("I couldn't finish handling your last message. Part of the request "
                    "may have already happened, so please check before resending."),
    "page.first_step": "FIRST STEP",
    "page.questions": "QUESTIONS FOR YOU · TEXT “Q2: …”",
    "page.sources": "Sources:",
    "page.could_not_source": "Couldn't source:",
    "page.nothing_to_report": "Nothing to report this time.",
    "page.advice_from": "Advice from",
    "page.priority_band": "What to prioritize today",
}

# Curated Portuguese: the paper's first language, never left to a translation.
PORTUGUESE = {
    "chat.busy": "⏳ Um instante — tô nessa.",
    "chat.busy_still": "⏳ Ainda nisso — já já eu falo.",
    "print.lede": "página não impressa — ",
    "print.retry": "; a próxima edição agendada tenta de novo",
    "print.timeout": "resultado desconhecido: ainda em execução após {seconds}s",
    "print.no_pdf": "nenhum PDF para imprimir em {path}",
    "turn.failed": ("Não consegui terminar de tratar sua última mensagem. Parte do pedido "
                    "pode já ter acontecido — confira antes de mandar de novo."),
    "page.first_step": "PRIMEIRO PASSO",
    "page.questions": "PERGUNTAS PARA VOCÊ · RESPONDA “Q2: …”",
    "page.sources": "Fontes:",
    "page.could_not_source": "Sem fonte:",
    "page.nothing_to_report": "Nada a relatar desta vez.",
    "page.advice_from": "Conselho de",
    "page.priority_band": "O que priorizar hoje",
}


def phrases_file():
    return pt_home() / "owner-phrases.json"


def current_language():
    return _gate.owner_language(config_file())


def is_english(language):
    tag = (language or "").lower().replace("_", "-")
    return "english" in tag or "ingl" in tag or tag == "en" or tag.startswith("en-")


def _placeholders(text):
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name)


def _stored():
    try:
        data = json.loads(phrases_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("phrases"), dict):
        return None
    return data


def table(language=None):
    """The table for this owner: their written phrases, else curated pt/en."""
    language = current_language() if language is None else language
    stored = _stored()
    if stored and language and stored.get("language") == language and not problems(stored["phrases"]):
        return stored["phrases"]
    return PORTUGUESE if is_portuguese(language) else SOURCE


def phrase(key, language=None, **fields):
    text = table(language)[key]
    return text.format(**fields) if fields else text


def status(language=None):
    language = current_language() if language is None else language
    if language and (is_english(language) or is_portuguese(language)):
        return "ready"
    stored = _stored()
    ok = stored and language and stored.get("language") == language and not problems(stored["phrases"])
    return "ready" if ok else "missing"


def problems(candidate):
    """Why a translation is not usable, first reason first; [] when it is."""
    if not isinstance(candidate, dict):
        return ["phrases is not an object"]
    found = []
    for key in SOURCE:
        if key not in candidate:
            found.append(f"missing: {key}")
        elif not isinstance(candidate[key], str) or not candidate[key].strip():
            found.append(f"blank: {key}")
        elif _placeholders(candidate[key]) != _placeholders(SOURCE[key]):
            found.append(f"placeholders differ: {key}")
    found += [f"unknown: {key}" for key in candidate if key not in SOURCE]
    return found


def record(raw):
    language = current_language()
    if not language:
        raise ValueError("no owner.language recorded yet; record it first")
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise ValueError(f"not JSON: {error}") from None
    candidate = data.get("phrases") if isinstance(data, dict) else None
    found = problems(candidate)
    if found:
        raise ValueError("; ".join(found))
    path = phrases_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"language": language, "phrases": candidate}, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["template"]:
        print(json.dumps({"language": current_language(), "phrases": SOURCE}, ensure_ascii=False))
        return 0
    if argv == ["status"]:
        print(f"PHRASES:{status()}")
        return 0
    if argv == ["record"]:
        try:
            record(sys.stdin.read())
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print("PHRASES:ready")
        return 0
    print("usage: owner_phrases.py template | record | status", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
