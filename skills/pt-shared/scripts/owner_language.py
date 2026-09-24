"""owner_language.py -- the one place that decides the owner's language.

Not a flow script: a library the pt-* scripts import. `record_owner_language.py`
writes `owner.language`; this reads it, for the mechanical lines that are
repo-authored copy rather than model prose (the chat wait lines, the
print-miss line, the priority card's date line).

One predicate, so `pt-PT`, `pt_AO` and `pt-BR` owners all get the same
Portuguese copy from the same config value.
"""
from __future__ import annotations


def is_portuguese(language):
    """True for every Portuguese tag, not an allow-list of regions.

    Accepts the plain-English name `record_owner_language.py` stores
    ("Português"), the bare tag, and every region: pt-BR, pt-PT, pt-AO, and
    the underscore forms a runtime sometimes passes through.
    """
    tag = (language or "").lower().replace("_", "-")
    return "portug" in tag or tag == "pt" or tag.startswith("pt-")
