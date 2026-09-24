"""The 402 wall is one pinned line, not Hermes' provider-specific concat."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_billing_user_message_is_the_short_line():
    mod = _load("billing_user_message", ROOT / "image/hermes/billing_user_message.py")
    assert mod.BILLING_USER_MESSAGE == (
        "Saldo da inferência acabou. Recarrega os créditos e tenta de novo."
    )
    lowered = mod.BILLING_USER_MESSAGE.lower()
    for leaked in ("openrouter", "http 402", "/model", "in-flight", "google/gemini"):
        assert leaked not in lowered


def test_patcher_rewrites_every_billing_concat_to_the_same_line():
    patcher = _load("patch_billing", ROOT / "image/hermes/patch_billing_user_message.py")
    source = "".join(old for old, _ in patcher.REPLACEMENTS)
    patched = patcher.apply(source)
    assert "Billing or credits exhausted: {summary}" not in patched
    assert patched.count("return BILLING_USER_MESSAGE") >= 2
    assert patched.count("final = BILLING_USER_MESSAGE") == 1
    assert '"error": final,' in patched
    assert '"error": summary,' not in patched
    assert "return None\n    try:" in patched


def test_patcher_refuses_a_moved_hermes_source():
    patcher = _load("patch_billing", ROOT / "image/hermes/patch_billing_user_message.py")
    try:
        patcher.apply("not the conversation loop")
    except SystemExit as exc:
        assert "did not match" in str(exc)
    else:
        raise AssertionError("expected the pin to refuse a source without markers")


def test_dockerfile_applies_the_billing_pin_at_build():
    text = (ROOT / "Dockerfile").read_text()
    assert (
        "COPY image/hermes/billing_user_message.py /opt/hermes/agent/billing_user_message.py"
        in text
    )
    assert "patch_billing_user_message.py" in text
    assert "/opt/hermes/agent/conversation_loop.py" in text
