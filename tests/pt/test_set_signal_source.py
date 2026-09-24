"""set_signal_source.py -- the owner switches one signal source on or off after setup."""
from __future__ import annotations

import contextlib
import io
import json

import pytest

from conftest import load_module

switch = load_module("set_signal_source", "pt-shared/scripts/set_signal_source.py")

READY = {
    "owner": {"timezone": "America/Sao_Paulo", "language": "Portuguese"},
    "delivery": {"hour": "07:00", "lead_minutes": 150},
    "printer": {"configured": False, "name": None},
    "priority": {"configured": True},
    "mail": {"configured": True},
}


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    path = tmp_path / "config.json"
    path.write_text(json.dumps(READY))
    return path


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = switch.main(list(argv))
    return code, out.getvalue().strip(), err.getvalue().strip()


def test_on_creates_the_block_with_the_other_sources_off(config):
    assert run("email", "on") == (0, "SIGNALS:group_chat=off,email=on,imessage=off", "")
    written = json.loads(config.read_text())
    assert written["signals"] == {"group_chat": False, "email": True, "imessage": False}
    assert {k: v for k, v in written.items() if k != "signals"} == READY


def test_off_keeps_the_other_switches(config):
    run("group_chat", "on")
    run("imessage", "on")
    assert run("group_chat", "off")[1] == "SIGNALS:group_chat=off,email=off,imessage=on"


@pytest.mark.parametrize("argv", [("sms", "on"), ("email", "yes"), ("email",), ()])
def test_bad_arguments_change_nothing(config, argv):
    code, out, err = run(*argv)
    assert code == 1 and out == "" and err.startswith("error:")
    assert json.loads(config.read_text()) == READY


def test_missing_config_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("PT_HOME", str(tmp_path))
    code, _, err = run("email", "on")
    assert code == 1 and "no config" in err
    assert not (tmp_path / "config.json").exists()


def test_a_config_the_gate_refuses_is_left_alone(config):
    config.write_text(json.dumps({**READY, "delivery": {"hour": "25:00"}}))
    before = config.read_text()
    code, _, err = run("email", "on")
    assert code == 1 and "delivery.hour" in err
    assert config.read_text() == before
