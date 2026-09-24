#!/usr/bin/env python3
"""Shared structural gate for the pt-config (the Founder Times' pt/config.json).

This is the SINGLE shared definition of "installed" for the pt-config. It runs
in the agent container, invoked as:

    python3 .../pt-shared/scripts/pt_config_gate.py <config.json>

at setup time (after pt-setup writes the config) and before anything schedules
against it, so the structural contract lives in one place, single-homed with
references/config.example.json, and no caller can drift from it.

Output contract (the ld_config_gate.py shape, minus the jq-equivalence
requirement this repo does not carry):
  - Prints the failing invariant name(s) to stdout, joined by "; ".
  - Empty stdout == PASS. Never prints anything else on pass.
  - Prints exactly "not valid JSON" (and nothing else) when the file does not
    parse as JSON, is unreadable, or has a shape the checks themselves could
    not inspect (indexing a non-object, testing a non-string).
  - Never prints PII. There is none by design: the config holds a timezone, a
    delivery hour, and whether a printer exists.

The ten checks:
  1. owner.timezone must contain a non-whitespace char. register_crons.py
     refuses to register unless the container's TZ equals it, and SOUL.md
     routes first-run onboarding from the keys' presence -- a blank one
     satisfies neither.
  2. delivery.hour must be the exact "HH:MM" shape (00-23 : 00-59). The cron
     spec is built as "<minute> <hour> * * *" from both parts -- a bare cron
     expression is already minute-precise (the lead-time subtraction for the
     daily paper has always produced a non-zero minute field), so any real
     "HH:MM" is a real promise the schedule can keep; only the shape itself
     is refused here.
  3. printer.configured must be a boolean. It is the print path's only gate,
     so a truthy string ("false" reads truthy) would hand pt-print a printer
     that does not exist -- a print leg that fails on every nightly run.
  4. printer.name must be a non-blank string when configured is true: `lp -d`
     needs a destination. When configured is false, name may be null or
     absent.
  5. delivery.lead_minutes, when present, is a non-negative integer: it is how many
     minutes before delivery.hour the daily paper's run starts, and a bool
     (True is an int in Python), a string, or a negative would not be a
     number of minutes. How far back is too far is register_crons.py's call:
     daily_schedule() refuses a run before midnight of its day. Absent
     is valid -- readers default it to 0, so an install written before the
     key existed does not start failing this gate.
  6. delivery.extra_hours, when present, is a list of "HH:MM" strings: one
     more full-paper delivery time the same day (register_crons.py registers
     one job per entry, numbered pt-daily-edition-2, -3, ...). Absent is
     valid -- one delivery a day is the common case.
  7. owner.language, when present, is a non-blank string: the language the
     owner writes to this agent in, plain-English name ("Portuguese",
     "Mandarin Chinese"), kept current by pt-intake on every turn so a
     scheduled edition -- which has no live message to detect a language
     from -- still writes in whatever the owner most recently used. Absent
     is valid: an install that predates this field, or one where the owner
     has only ever written in one language pt-intake hasn't needed to
     record yet, defaults elsewhere (pt-edition) rather than failing here.
  8. mail.configured, when the mail object is present, must be a boolean.
     Absent mail is valid and means the letters desk is off -- this agent
     does not invent an inbox. True means the daily paper reads today's
     mail through Latch (Gmail via plow-gog first, Mail.app if that fails);
     false is an explicit no.
  9. no string value anywhere may be a leftover [UPPER_SNAKE] placeholder.
  10. priority, when present, has a boolean `configured`. Absent priority
     is valid and means the desk is off.

The owner's name, location, or any other personal fact is deliberately not
among the checks, and not in the schema: location is fetched each run via
Latch and printed that day, never stored here. The durable record is still
the topics, these delivery preferences, language, and whether mail is on.
"""
import json
import re
import sys

_PLACEHOLDER_RE = re.compile(r"^\[[A-Z][A-Z0-9_]*\]$")
_NONBLANK_RE = re.compile(r"\S")
# The only shape the delivery hour may take: any real "HH:MM". A bare cron
# expression is minute-precise ("<minute> <hour> * * *"), and the daily
# paper's own lead-time subtraction has always produced a non-zero minute
# field -- there was never a mechanical reason to hold the OWNER's chosen
# minute to :00 while accepting any minute computed internally. Previously
# restricted to ":00" on the theory that "the cron fires at the hour" was a
# hard limit; measured against register_crons.py's own daily_schedule(), it
# never was one.
_DELIVERY_HOUR_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


class GateError(Exception):
    """A structural shape the checks themselves cannot inspect.

    Collapses to "not valid JSON" in main(), exactly as the jq-era gate
    collapsed a filter-level error and a parse failure into that one line.
    """


SIGNAL_SOURCES = ("group_chat", "email", "imessage")


def _index(value, key):
    """dict get with a loud refusal on non-object shapes."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(key)
    raise GateError("cannot index non-object")


def _nonblank(value):
    """True when value is a string containing a non-whitespace char."""
    if not isinstance(value, str):
        raise GateError("non-string where a string is required")
    return bool(_NONBLANK_RE.search(value))


def _all_strings(node):
    """Every string reachable by recursive descent."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _all_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _all_strings(v)


def gate(config):
    """Return the "; "-joined failures for a parsed config (empty == pass).

    Raises GateError for shapes the checks cannot inspect; the caller maps
    that to "not valid JSON".
    """
    failures = []

    # 1. owner.timezone non-blank -- the zone every schedule is written
    #    against and the one thing pt-setup must confirm out loud.
    tz = _index(_index(config, "owner"), "timezone")
    if not _nonblank(tz):
        failures.append("owner.timezone is blank")

    # 2. delivery.hour is a real "HH:MM". See _DELIVERY_HOUR_RE for why any
    #    minute is accepted, not just :00.
    hour = _index(_index(config, "delivery"), "hour")
    if not (isinstance(hour, str) and _DELIVERY_HOUR_RE.fullmatch(hour)):
        failures.append('delivery.hour is not "HH:MM"')

    # 3. printer.configured is a boolean, unambiguously.
    configured = _index(_index(config, "printer"), "configured")
    if not isinstance(configured, bool):
        failures.append("printer.configured is not a boolean")

    # 4. a configured printer has a name; an unconfigured one may not.
    if configured is True:
        name = _index(_index(config, "printer"), "name")
        if not _nonblank(name):
            failures.append("printer.name is blank while printer.configured is true")

    # 5. delivery.lead_minutes, when present, is a non-negative int. Absent stays
    #    valid: the daily-paper readers apply the 0-minute default, so an
    #    install written before this key existed keeps passing the gate.
    lead = _index(_index(config, "delivery"), "lead_minutes")
    if lead is not None:
        # bool is a subclass of int -- True is 1, False is 0, and neither is
        # a number of minutes. Refused explicitly, not silently accepted.
        if isinstance(lead, bool) or not isinstance(lead, int) or lead < 0:
            failures.append("delivery.lead_minutes is not a non-negative integer")

    # 6. delivery.extra_hours, when present, is a list of real "HH:MM"
    #    strings -- one more full-paper delivery time the same day (e.g. a
    #    second edition at 10:30 as well as the morning one). Absent stays
    #    valid: one delivery a day is the common case and needs no key at
    #    all. Each entry is held to the same shape as delivery.hour itself,
    #    for the same reason -- register_crons.py builds a real cron
    #    expression from it.
    extra_hours = _index(_index(config, "delivery"), "extra_hours")
    if extra_hours is not None:
        if not isinstance(extra_hours, list) or not all(
            isinstance(h, str) and _DELIVERY_HOUR_RE.fullmatch(h) for h in extra_hours
        ):
            failures.append('delivery.extra_hours is not a list of "HH:MM" strings')

    # 7. owner.language, when present, is non-blank. Absent is valid --
    #    pt-edition falls back elsewhere, and pt-intake sets this the first
    #    time it has an owner message to detect a language from.
    language = _index(_index(config, "owner"), "language")
    if language is not None and not _nonblank(language):
        failures.append("owner.language is blank")

    # 8. mail.configured, when mail is present, is a boolean. Absent mail
    #    is an unconfigured letters desk -- the daily paper skips it.
    mail = _index(config, "mail")
    if mail is not None:
        mail_configured = _index(mail, "configured")
        if not isinstance(mail_configured, bool):
            failures.append("mail.configured is not a boolean")

    # 10. priority, when present, is a boolean switch. Absent means the desk is
    #     off. Its pages live at fixed paths in the owner's wiki (wiki.py).
    priority = _index(config, "priority")
    if priority is not None and not isinstance(_index(priority, "configured"), bool):
        failures.append("priority.configured is not a boolean")

    # 11. signals, when present, switches the priority-signal sources: an
    #     object whose keys are group_chat / email / imessage, each a boolean.
    #     Absent means every source is off (an install from before signals).
    signals = _index(config, "signals")
    if signals is not None:
        if not isinstance(signals, dict):
            failures.append("signals is not an object")
        else:
            for source, switch in signals.items():
                if source not in SIGNAL_SOURCES:
                    failures.append(f"signals.{source} is not a signal source")
                elif not isinstance(switch, bool):
                    failures.append(f"signals.{source} is not a boolean")

    # 9. no leftover [UPPER_SNAKE] placeholder anywhere.
    if any(_PLACEHOLDER_RE.match(s) for s in _all_strings(config)):
        failures.append("an unfilled [UPPER_SNAKE] placeholder remains")

    return "; ".join(failures)


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: pt_config_gate.py <config.json>\n")
        return 2
    try:
        with open(argv[1], encoding="utf-8") as f:
            # parse_constant fail-closes NaN/Infinity the same way the ld
            # gate does: both parsers accept the non-standard tokens, and a
            # config that parse but cannot be trusted is not valid here.
            config = json.load(
                f, parse_constant=lambda token: (_ for _ in ()).throw(
                    ValueError(f"non-standard JSON constant {token}")))
        failures = gate(config)
    except (OSError, ValueError, GateError):
        print("not valid JSON")
        return 0
    if failures:
        print(failures)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))