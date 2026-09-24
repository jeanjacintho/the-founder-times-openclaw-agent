"""owner_language.py -- the one policy for "is this owner writing Portuguese?"

This is where the tag matrix lives. Its consumers (the chat wait lines, the
unavailable-paper notice) each assert only that they route through it, not
the tag rules again.
"""
from __future__ import annotations

import pytest

from conftest import load_module

lang = load_module("owner_language", "pt-shared/scripts/owner_language.py")


@pytest.mark.parametrize("language, portuguese", [
    ("pt", True),
    ("pt-BR", True),
    ("pt-PT", True),          # European -- an allow-list of two missed it
    ("pt-AO", True),          # Angolan
    ("pt_BR", True),          # underscore form Hermes sometimes passes through
    ("pt_AO", True),
    ("PT-br", True),          # case is not significant
    ("Português", True),      # the name record_owner_language.py stores
    ("portuguese", True),
    ("en", False),
    ("en-GB", False),
    ("English", False),
    ("es-MX", False),         # Spanish, and notably not a pt- prefix
    ("pts", False),           # merely starting with "pt" is not Portuguese
    ("ptolemaic", False),
    ("", False),
    (None, False),
])
def test_which_tags_are_portuguese(language, portuguese):
    assert lang.is_portuguese(language) is portuguese
