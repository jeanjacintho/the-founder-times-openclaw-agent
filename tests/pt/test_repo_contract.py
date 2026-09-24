"""Repo-level deployment contracts: plow-agents compose.yml and the image."""
from __future__ import annotations

import json
import os
import pathlib
import stat

from conftest import ROOT, load_module

import pytest

# These contracts describe the previous runtime image (compose, s6, the Hermes
# venv). They are rewritten against the OpenClaw layout; until then they stay
# out of the run rather than failing on paths that no longer exist.
pytestmark = pytest.mark.skip(reason="previous-runtime repo contract, pending rewrite for OpenClaw")


class TestSoul:
    def test_soul_md_does_not_trip_hermes_context_injection_scanner(self):
        # Measured live: agent.prompt_builder scans SOUL.md before it ever
        # reaches the model (tools/threat_patterns.py, scope="context") and
        # replaces the WHOLE file with "[BLOCKED: ... prompt injection ...]"
        # on a hit -- not a warning, a silent full-file drop. SOUL.md's own
        # advice to distrust web content ("a page that says 'ignore your
        # previous instructions'...") tripped its own guard's
        # "prompt_injection" pattern, so the agent ran with NONE of its
        # instructions (no pt-intake, no sourcing rule, nothing) while every
        # skill file and this repo's own tests stayed green -- the failure
        # was invisible to anything except the gateway's own runtime log.
        # This mirrors that one pattern (the exact regex that fired), not
        # the full scanner, as a cheap regression guard with no dependency
        # on the hermes_agent package being installed.
        import re

        pattern = re.compile(
            r"ignore\s+(?:\w+\s+){0,8}(previous|all|above|prior)\s+(?:\w+\s+){0,8}instructions",
            re.IGNORECASE,
        )
        text = (ROOT / "runtime" / "SOUL.md").read_text()
        assert not pattern.search(text), (
            "SOUL.md contains a phrase matching Hermes' context-injection "
            "scanner (tools/threat_patterns.py, pattern id 'prompt_injection'); "
            "the whole file gets replaced with a [BLOCKED: ...] placeholder "
            "at runtime, not just this sentence -- reword it, don't just "
            "silence this assertion"
        )

    def test_soul_fits_hermes_context_file_limit(self):
        # Measured live: prompt_builder truncated SOUL.md at 20 000 because
        # context_file_max_chars never reached plow-seed. The merge carries
        # the runtime value; this bound uses the same number so a longer
        # persona fails here instead of only in docker compose logs.
        check = load_module("soul_fits_context", "checks/soul_fits_context.py")
        n, limit = check.check(ROOT)
        assert n <= limit, f"SOUL.md is {n} chars; Hermes truncates above {limit}"

    def test_soul_forbids_reading_the_agents_own_env_file(self):
        # Measured live: asked why a page had not printed, a session reached
        # for execute_code three times to read /var/lib/hermes/.env (once via
        # read_file, twice via terminal cat) and put the raw /approve prompt
        # in front of the owner each time. That file is the agent's own
        # credential store -- an approval would have printed credentials into
        # the chat transcript. The rule has to name the path, because the
        # existing never-improvise prose did not.
        text = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "/var/lib/hermes/.env" in text
        assert "Never read" in text

    def test_print_skill_says_a_hosted_install_can_print(self):
        # A hosted install used to fail every print on a missing DOMO_* pair,
        # and the skill told the owner paper was unavailable on their install.
        # connect() now derives the relay URL from the agent's own credential,
        # so that state does not exist and the skill must not claim it does --
        # nor may post_to_chat.py still carry a terminal marker for it.
        text = (ROOT / "pt-print" / "SKILL.md").read_text()
        assert "no state in which paper can never print" in text
        assert "/v1/agents/me" in text
        assert "paper is unavailable" not in text
        post = (ROOT / "pt-shared" / "scripts" / "post_to_chat.py").read_text()
        assert "paper is unavailable" not in post

    def test_setup_opener_does_not_ask_timezone(self):
        text = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert "A que horas você quer o jornal de manhã?" in text
        assert "Qual seu fuso" not in text

    def test_soul_setup_gate_is_a_bare_script_not_python_dash_c(self):
        text = (ROOT / "runtime" / "SOUL.md").read_text()
        assert (
            "/var/lib/hermes/skills/pt-shared/scripts/setup_needed.py "
            "/var/lib/hermes/pt/config.json"
        ) in text
        assert "python3 -c" not in text
        assert "bash -c" not in text
        text = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "not a first-contact script" in text
        assert "pt-setup" in text

    def test_soul_setup_gate_applies_to_every_reply_not_just_greetings(self):
        # Measured live: right after "Is a printer set up on your Mac?"
        # was answered "Yes", a session skipped the setup_needed.py check
        # entirely on that reply and went straight to an unprompted inline
        # Python read of pt/config.json (which doesn't exist yet at that
        # point) wrapped in a heredoc -- tripping the dangerous-command
        # gate for a file read nothing asked for.
        text = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "every single reply" in text
        assert "a reason to reach for inline" in text
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert "ad-hoc Python" in setup or "ad-hoc script" in setup

    def test_setup_latch_probe_uses_argv_not_command(self):
        # Latch plow_run_command (tools.ts) requires argv and
        # additionalProperties: false. A "command" key never reaches lpstat.
        text = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert '"command":' not in text
        assert '"argv": ["lpstat", "-p"]' in text
        assert "mcp__plow__plow_run_command" in text

    def test_setup_printer_probe_requests_network_for_cups_ipc(self):
        # Root cause, reproduced directly against Latch's generated profile
        # on a real Mac: lpstat reaches cupsd over a local Unix domain
        # socket, and the seatbelt profile grants network*/system-socket
        # only when `network` is true. Without the flag CUPS cannot open
        # the socket to its own scheduler and libcups reports "Bad file
        # descriptor". Deterministic, not flaky: 25/25 pass with the flag,
        # 10/10 fail without it, and a plain shell outside Latch always
        # passes. `network: true` is the workaround from this side (the
        # scoped fix belongs in Latch's own sandbox profile, not here).
        text = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert '"network": true' in text
        assert "Bad file descriptor" in text
        # The flag covers local IPC, not just remote access — the whole
        # reason this looked like a CUPS fault for so long.
        assert "local IPC" in text

    def test_setup_printer_probe_falls_back_to_plow_run_applescript(self):
        # Root cause, measured three runs back to back on the owner's Mac:
        # cupsd is launchd-on-demand, and a SANDBOXED lpstat cannot trigger
        # the rendezvous that starts it. cupsd asleep + sandbox => "Bad file
        # descriptor", and it stays asleep; unsandboxed => works AND starts
        # it; sandboxed immediately after => works. That is the whole
        # "intermittent" story, and Latch's audit log shows it directly:
        # same argv, same "Network: allowed", exit 0 at 01:00 and exit 1 at
        # 01:12. So network:true is necessary but NOT sufficient, and the
        # retry must go through plow_run_applescript -- the tool that really
        # runs outside the sandbox -- which also wakes cupsd for later runs.
        text = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert "plow_run_applescript" in text
        assert '"app": "System Events"' in text
        assert "necessary but NOT sufficient" in text
        assert "launchd" in text

    def test_setup_printer_probe_never_runs_osascript_via_run_command(self):
        # The retry that could only ever fail: osascript handed to
        # plow_run_command is an ordinary process.exec intent and runs under
        # sandbox-exec, so it inherited the identical denial and reproduced
        # the identical error one layer down. Inside the printer probe it may
        # appear ONLY as the documented warning, never as an instruction.
        text = (ROOT / "pt-setup" / "SKILL.md").read_text()
        probe = text[text.index('"argv": ["lpstat", "-p"]'):text.index("record_setup.py /var/lib/hermes/pt/config.json printer.configured=true")]
        assert probe.count('["osascript"') == 1, "osascript appears in the probe other than as the warning"
        assert probe.index("Do not") < probe.index('["osascript"')

    def test_pt_shared_documents_every_script_it_ships(self):
        # Measured live, at the news-desk step: a session ran
        # `python3 -c "...record_setup.py').read_text()"` -- reading a flow
        # script's OWN SOURCE to work out how to call it -- and handed the
        # owner an /approve prompt instead of the next question. Root cause:
        # record_setup.py was the one script in pt-shared/scripts absent from
        # pt-shared/SKILL.md's inventory, and it is the most-invoked script
        # in the setup flow. An interface nobody documents is one a run will
        # go read. Every script in the directory must carry a bullet.
        listed = (ROOT / "pt-shared" / "SKILL.md").read_text()
        shipped = sorted(p.name for p in (ROOT / "pt-shared" / "scripts").glob("*.py"))
        assert shipped, "no scripts found -- path wrong, test is vacuous"
        missing = [n for n in shipped if n not in listed]
        assert not missing, f"undocumented pt-shared scripts: {missing}"

    def test_soul_forbids_reading_flow_script_source(self):
        # The guard used to cover wrapping an invocation and reading
        # config.json, but never "read the script to learn its interface" --
        # the one variant with an actual motive behind it.
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "own source" in soul
        assert "Never open one of these scripts" in soul
        # And it must point at where the contract actually lives.
        assert "pt-shared" in soul

    def test_language_is_a_recorded_fact_not_a_prose_reminder(self):
        # Four live drifts: three failure explanations and one printer
        # SUCCESS reply, the last in Dutch, all in interviews written wholly
        # in English. Each drift was answered by attaching a reminder to that
        # branch -- and the next drift arrived on a branch without one. The
        # gate already runs as the first action of every reply, so the
        # recorded language rides back on every one of them.
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert "owner.language=" in setup, "the interview must record the language"
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "LANG:unrecorded" in soul
        # And the gate must actually emit it.
        gate = (ROOT / "pt-shared" / "scripts" / "setup_needed.py").read_text()
        assert "def language_line" in gate
        assert "LANG:" in gate
        # ...and it must survive into the config a scheduled edition reads.
        assert '"language"' in (ROOT / "pt-setup" / "scripts" / "finalize_setup.py").read_text()
        intake = (ROOT / "pt-intake" / "SKILL.md").read_text()
        assert "record_owner_language.py" in intake

    def test_on_demand_copy_is_routed_and_not_filed_as_a_topic(self):
        # Measured live: "generate a copy for me to read right now" had no
        # route -- pt-intake's five rows are all "a new subject to research"
        # -- so it became a one_off topic reading "A current copy of my daily
        # newspaper" and the research pass went looking for that phrase on the
        # web. The paper came back with the standing desks and a news block
        # saying "No separate news desk in this quick pass", while 48 saved
        # sections went unread: a one-off edition carries only its own topic.
        intake = (ROOT / "pt-intake" / "SKILL.md").read_text()
        assert "not a topic" in intake, "the on-demand row is missing from the routing table"
        edition = (ROOT / "pt-edition" / "SKILL.md").read_text()
        assert "## On demand" in edition
        # It must queue the cron's own job, never restate its steps: a second
        # copy of those steps is a second thing to keep in sync.
        assert "register_crons.py --now" in edition
        assert "register_crons.py --now" in intake
        crons = (ROOT / "pt-dashboard" / "scripts" / "register_crons.py").read_text()
        assert '"--now"' in crons

    def test_render_step_gives_complete_commands_not_a_merge(self):
        # Measured live: the render step showed ONE command plus a comment
        # ("# add --html PATH too when a printer is configured"), so a run
        # with a printer had to assemble its own argv -- and lost --pdf while
        # inventing a valueless --chat (exit 2). It rendered edition.html and
        # edition.chat.txt, no PDF, and posted text. weasyprint 62.3 was
        # installed and working on that machine.
        text = (ROOT / "pt-edition" / "SKILL.md").read_text()
        assert "# add --html PATH too" not in text, "the merge-a-comment form is back"
        render = [
            line.strip()
            for line in text.splitlines()
            if "render_edition.py" in line and line.startswith(" " * 7)
        ]
        # One command, printer or not: the print ships the same PDF, so a
        # printer-only --html variant is a choice the model can only get wrong.
        assert len(render) == 1, render
        assert "--pdf" in render[0] and "--html" not in render[0], render[0]

    def test_pdf_fallback_is_keyed_on_weasyprint_not_on_any_failure(self):
        # The fallback used to fire whenever "render_edition.py produced no
        # PDF", which a usage error satisfies -- so a typo silently demoted
        # the owner to plain text, permanently.
        import re

        text = (ROOT / "pt-edition" / "SKILL.md").read_text()
        flat = re.sub(r"\s+", " ", text.replace("*", ""))
        assert "not the weasyprint fallback" in flat
        assert "exit_code: 2" in flat

    def test_text_leg_needs_no_shell_redirect(self):
        # /bin/sh -c '... < edition.chat.txt' tripped the dangerous-command
        # gate. A flag needs no shell.
        text = (ROOT / "pt-edition" / "SKILL.md").read_text()
        assert "--text-file" in text
        script = (ROOT / "pt-shared" / "scripts" / "post_to_chat.py").read_text()
        assert '"--text-file"' in script

    def test_edition_post_prints_and_finalizes_itself(self):
        script = (ROOT / "pt-shared" / "scripts" / "post_to_chat.py").read_text()
        assert "print_page" in script
        assert "print_edition.py" in script
        edition = (ROOT / "pt-edition" / "SKILL.md").read_text()
        assert "print_edition.py" in edition
        assert "call `pt-print`" in edition
        assert "Do not mark topics after posting" in edition



    def test_close_step_names_a_command_for_writing_the_config(self):
        # Measured live: step 3 said "**Write** config.json from the draft"
        # and named no tool, and nothing in the tree wrote that file. A run
        # with every field it needed ran the gate against a file nobody had
        # created, got "not valid JSON" (what the gate says for a MISSING
        # file) and told the owner the setup hit a configuration error.
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert "finalize_setup.py" in setup
        assert "--owner-tz" in setup
        # The bare, un-actioned instruction must not come back.
        assert "**Write** `/var/lib/hermes/pt/config.json` from the draft" not in setup
        assert (ROOT / "pt-setup" / "scripts" / "finalize_setup.py").exists()

    def test_close_step_names_a_command_for_clearing_the_draft(self):
        # Measured live: the close step said "delete .setup-draft.json" and
        # named no command, so a run reached for an inline -c one-liner
        # calling os.remove and tripped the dangerous-command gate in front
        # of the owner -- with the newspaper otherwise finished. An
        # instruction with no affordance is the bug; the script that owns the
        # draft owns deleting it too.
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert "--done" in setup
        assert "os.remove" in setup, "the failure mode must stay named"
        # The bare, un-actioned instruction must not come back.
        assert "and delete `.setup-draft.json`." not in setup
        shared = (ROOT / "pt-shared" / "SKILL.md").read_text()
        assert "--done" in shared

    def test_soul_generalizes_the_missing_affordance_rule(self):
        # Two variants of one class (read a script's source; delete a file
        # with an interpreter). The guard must state the class, not just
        # enumerate the instances.
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "names no command" in soul
        assert "record_setup.py" in soul and "--done" in soul

    def test_no_skill_prefixes_an_interpreter_or_splits_a_command(self):
        # SOUL.md says "do not prefix an interpreter", and every one of these
        # scripts is executable with a shebang -- yet six SKILL.md examples
        # across four skills opened with `python3 ` and wrapped onto a second
        # line with a backslash. Measured live: given that shape, a run
        # reached for execute_code to run convert_delivery.py and tripped the
        # dangerous-command gate. An example that contradicts the rule is the
        # bug; the rule is right.
        for path in sorted(ROOT.glob("pt-*/SKILL.md")):
            text = path.read_text()
            assert "python3 /var/lib/hermes" not in text, f"interpreter prefix in {path.name}"
            for line in text.splitlines():
                if "/var/lib/hermes/skills/" in line and line.rstrip().endswith("\\"):
                    raise AssertionError(f"split script invocation in {path.name}: {line.strip()}")

    def test_every_bare_invoked_script_is_executable(self):
        # The SKILL.md examples name scripts by absolute path with no
        # interpreter, so each one must be executable and carry a shebang --
        # otherwise the documented command simply fails. render_edition.py was
        # mode 0644 when its `python3 ` prefix was removed, and only the
        # Dockerfile's `-perm -u+x` chmod would have carried the bit through.
        import re

        seen = set()
        for path in sorted(ROOT.glob("pt-*/SKILL.md")):
            for match in re.finditer(r"/var/lib/hermes/skills/(pt-[\w-]+/scripts/[\w.]+\.py)", path.read_text()):
                seen.add(match.group(1))
        assert seen, "no script invocations found -- regex is wrong, test is vacuous"
        for rel in sorted(seen):
            script = ROOT / rel
            assert script.exists(), f"{rel} is invoked but not in the tree"
            assert script.read_text().startswith("#!"), f"{rel} has no shebang"
            import os

            assert os.access(script, os.X_OK), f"{rel} is invoked bare but is not executable"

    def test_shebang_entry_scripts_are_executable_even_if_only_the_recipe_names_them(self):
        # Measured live 2026-09-17: an on-demand "exemplar impresso agora"
        # never started research. The daily recipe says "run pt-shared's
        # run_lock.py" (no interpreter). That file was 0644; bash returned
        # Permission denied (126). The model then opened the source and
        # wrapped python3, which tripped Hermes' /approve gate in a loop.
        # SKILL.md-only scanning misses this: the lock lives in
        # register_crons.py's printed recipe, not in a SKILL.md example.
        skip = {"bearer_http.py"}  # imported, never invoked bare
        missing = []
        for path in sorted(ROOT.glob("pt-*/scripts/*.py")):
            if path.name in skip:
                continue
            if not path.read_text().startswith("#!"):
                continue
            if not os.access(path, os.X_OK):
                missing.append(str(path.relative_to(ROOT)))
        assert not missing, (
            "shebang entry scripts must be executable; on-demand paper "
            f"stops at Permission denied otherwise: {missing}"
        )

    def test_soul_forbids_execute_code_for_flow_commands(self):
        # execute_code was the one route the guard never named: it enumerated
        # -c, heredocs, shells, ||, &&, ;, printf -- so the run picked the
        # door that wasn't on the list.
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "execute_code" in soul
        assert "shebang" in soul

    def test_research_web_is_latch_browser_only(self):
        # Measured live, 2026-09-17: an on-demand paper opened Latch for
        # the priority file, then spent ~70 tool turns on Hermes
        # web_extract / Firecrawl / Exa / Keenable / Parallel against
        # ESPN and F1 from the container. Those calls never hit the
        # owner's Mac. The paper's web is Latch's browser or it is not
        # sourced -- including sports JSON that desks.md used to call a
        # "plain HTTP fetch" that "does not compete for the browser pass".
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        research = (ROOT / "pt-research" / "SKILL.md").read_text()
        desks = (ROOT / "pt-research" / "references" / "desks.md").read_text()
        # SOUL.md, loaded in every session, is the one statement of the rule.
        for name in ("plow_browser_", "web_extract", "Firecrawl", "Exa", "Keenable", "Parallel"):
            assert name in soul
        assert "web_extract" not in research, "the Latch-only rule is restated in pt-research"
        assert "plain HTTP fetch" not in desks
        assert "does not compete for the browser pass" not in desks
        assert "plow_run_command can fetch this" not in desks
        assert "plow_browser" in desks
        assert "site.api.espn.com" in desks

    def test_research_one_browser_session_does_not_retry_origin_errors(self):
        # Measured live 2026-09-18: an on-demand paper spent ~30 minutes.
        # ipapi.co NS_ERROR_UNKNOWN_HOST every run; then plow_browser_request
        # with no origins ("needs origins and/or credential_items"); then
        # goto techcrunch.com while only *.techcrunch.com was allowlisted;
        # then MCP "Paused for ~44s" and the same call again. The contract:
        # one open for the whole paper, apex+wildcard together, fail once.
        research = (ROOT / "pt-research" / "SKILL.md").read_text()
        desks = (ROOT / "pt-research" / "references" / "desks.md").read_text()
        assert "needs origins" in research
        assert "apex" in research and "*.example.com" in research
        assert "Paused" in research
        assert "do not close" in desks or "Do not close" in desks
        assert "do not retry ipapi" in desks or "never retry ipapi" in desks

    def test_setup_warns_against_wrapping_record_setup_in_python(self):
        # Measured live: with a real printer found (network:true worked),
        # the assistant recorded a perfectly valid printer name by
        # wrapping record_setup.py in `python3 - <<'PY' ... PY` for no
        # technical reason -- there was nothing in the value that needed
        # it -- and Hermes correctly flagged it as dangerous script
        # execution, handing the owner a raw /approve prompt instead of
        # an answer. Both files must say plainly that a dotted/underscored
        # *value* never requires any wrapping.
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert "python3 - <<'PY'" in soul
        assert "wrap this in" in setup
        assert "taken verbatim" in setup

    def test_setup_reads_location_through_the_browser_not_run_command(self):
        # Measured live: /usr/bin/python3 (via xcrun) and a curl fallback
        # both failed under plow_run_command's sandbox -- xcrun's own dylib
        # blocked by the file-read allowlist, then DNS resolution blocked
        # even with network:true. plow_browser_* is a different code path
        # (a real, unsandboxed browser on the owner's Mac) and hits
        # neither restriction.
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        desks = (ROOT / "pt-research" / "references" / "desks.md").read_text()
        for text in (setup, desks):
            assert "plow_browser_open" in text
            assert "plow_browser_close" in text
        assert "xcrun" in desks
        assert "Could not resolve host" in desks
        assert '"/usr/bin/python3"' not in setup

    def test_setup_location_lookup_falls_back_past_a_dead_domain(self):
        # Measured live: even through plow_browser_*, ipapi.co alone came
        # back NS_ERROR_UNKNOWN_HOST on one owner's Mac -- a dead domain,
        # not a sandbox gap. The procedure must try other providers, not
        # give up (or retry the same host) after one goto error.
        # desks.md §1 owns the fallback order; setup runs its steps 2-3.
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        desks = (ROOT / "pt-research" / "references" / "desks.md").read_text()
        for text in (setup, desks):
            assert "ipapi.co" in text
            assert "ipwho.is" in text
            assert "ifconfig.co" in text
        assert "NS_ERROR_UNKNOWN_HOST" in desks
        assert "references/desks.md` §1" in setup

    def test_soul_warns_failure_replies_still_match_owner_language(self):
        # Measured live, three times now: an all-English interview got a
        # Portuguese reply anyway -- twice in plain-text failure messages,
        # once inside a `clarify` tool call's question text. The rule must
        # cover tool-produced owner-facing strings, not just plain text.
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "failure explanation" in soul
        assert "clarify" in soul

    def test_setup_close_step_forbids_asking_the_owner_for_a_city(self):
        # Measured live: on reaching NEXT_QUESTION=close, a run skipped
        # straight past plow_browser_open and used the `clarify` tool to
        # ask the owner what city they're in -- exactly what desks.md
        # already forbids. It also wandered through five unrelated skills
        # first. The close section needs its own explicit guard, not just
        # a cross-reference to desks.md's rule.
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        close = setup.split("## Close:", 1)[1]
        assert "clarify" in close
        assert "Em que cidade" in close or "do only the three numbered" in close

    def test_setup_never_narrates_its_own_step_classification(self):
        # Measured live, TWICE: a bare "Oi" got back a paragraph classifying
        # the message and naming the step number, in English, stacked in
        # front of the actual Portuguese opener. Told to stop, the second
        # "Oi" got a reworded version of the identical violation -- proof
        # the fix has to be a mechanical check (first character of the
        # reply must be the opener's own first character), not a sentence
        # to avoid repeating.
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        # SOUL.md owns the mechanical check; pt-setup defers to it.
        assert "and only that message" in setup
        assert "nothing else — never" in soul
        assert "your own reasoning about which step" in soul
        assert "reworded version of the same thing" in soul
        assert "first character must be the catalog emoji" in soul

    def test_soul_reapplies_language_and_silence_rules_after_setup_is_ready(self):
        # Measured live: a whole setup interview ran correctly in Portuguese,
        # then the very next request -- "send me a paper now", answered live
        # with the owner watching -- narrated its entire research and print
        # run in English. READY used to print no LANG line; it now does,
        # and no skill outside pt-setup had ever been told to stay silent
        # between tool calls.
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "still prints" in soul and "LANG:" in soul
        assert "record_owner_language.py" in soul
        assert "silent between tool calls" in soul
        assert "register_crons.py --now" in soul
        # Issue #4: a lone no/não was recorded as a language change.
        for text in (soul, (ROOT / "pt-shared" / "SKILL.md").read_text()):
            assert "`no`" in text and "`não`" in text and "`nao`" in text

    def test_silence_between_tool_calls_is_stated_once(self):
        # No paper runs in the chat turn any more (#98); the silence rule is
        # SOUL.md's, loaded in every session, not restated per skill.
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "silent between tool calls" in soul
        for skill in ("pt-research", "pt-edition", "pt-print"):
            text = (ROOT / skill / "SKILL.md").read_text()
            for restated in ("run silently", "runs silently", "happen silently", "between tool calls"):
                assert restated not in text.lower(), f"{skill} restates the silence rule"

    def test_print_skill_ships_html_through_print_edition_not_the_model(self):
        # Measured live 2026-09-17: the model cat'd edition.html (~43k) then
        # tried to paste it into plow_write_file's content. The LLM stream
        # died (RemoteProtocolError / incomplete chunked read) twice; lp
        # never ran. Chat still worked because post_to_chat.py reads the
        # PDF from disk. Print must be the same shape: one bare script,
        # HTML stays in the file, never in a tool-call argument.
        text = (ROOT / "pt-print" / "SKILL.md").read_text()
        assert "post_to_chat.py` runs this" in text
        assert (
            "/var/lib/hermes/skills/pt-print/scripts/print_edition.py"
        ) in text
        assert "one `cat`, once" not in text
        assert "content=<the HTML>" not in text
        assert "plow_write_file" not in text
        script = ROOT / "pt-print" / "scripts" / "print_edition.py"
        assert script.is_file()
        assert script.read_text().startswith("#!")
        import os
        assert os.access(script, os.X_OK)

    def test_on_demand_paper_is_acknowledged_in_one_line(self):
        # Measured live: a paper built inside the chat turn posted every
        # research decision into chat, then attached edition.pdf. The turn
        # now only queues the job and answers with one ⏳ line.
        intake = (ROOT / "pt-intake" / "SKILL.md").read_text()
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        edition = (ROOT / "pt-edition" / "SKILL.md").read_text()
        assert "one ⏳ line" in intake
        assert "interim_assistant_messages: false" in soul
        assert "The-Founder-Times-" in edition
        assert "--filename" in edition
        script = ROOT / "pt-shared" / "scripts" / "chat_status.py"
        assert script.is_file()
        assert script.read_text().startswith("#!")
        import os
        assert os.access(script, os.X_OK)

    def test_owner_chat_voice_is_emoji_then_plain_speech(self):
        # Measured live 2026-09-18: setup was correct but read as a
        # product spec ("news desk", "~/Plow/prioritization.md",
        # "departments"). Real people get one emoji, a space, then a
        # spoken line — no paths, no desk names.
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        status = (ROOT / "pt-shared" / "scripts" / "chat_status.py").read_text()
        assert "CHAT_VOICE" in soul
        assert "emoji, then a space, then one or two short spoken lines" in soul
        for mark in ("📰", "🕖", "🖨️", "⭐", "✉️", "🗞️", "⏳"):
            assert mark in soul
        assert "> 📰 " in setup
        assert "> 🕖 " in setup
        assert "> 🖨️ " in setup
        assert "> ⭐ " in setup
        assert "> ✉️ " in setup
        assert "> 🗞️ " in setup
        spoken = "\n".join(
            line for line in setup.splitlines() if line.startswith("> ")
        )
        assert "~/" not in spoken
        assert "news desk" not in spoken.lower()
        assert '"⏳ ' in status
        assert "--busy" in status

    def test_setup_posts_a_hang_on_while_latch_work_runs(self):
        # Typed mid-turn text is dropped on plow_chat. Slow setup work
        # (printer probe, Mac files, location) has to POST a hang-on
        # through chat_status.py --busy, never a play-by-play.
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "chat_status.py --busy" in setup
        assert "chat_status.py --busy" in soul
        assert "do not type" in setup.lower() or "never type" in setup.lower()

    def test_setup_treats_yes_as_the_default_hour(self):
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert "send its opener" not in soul
        # SOUL.md delegates to pt-setup's own NEXT_QUESTION-driven steps
        # rather than duplicating the "yes"/07:00 acceptance list itself —
        # two descriptions of the same rule is how they drifted apart
        # before. pt-setup/SKILL.md is the one place that rule lives.
        assert "record_setup.py" in soul and "NEXT_QUESTION" in soul
        assert '"yes"' in setup and '"sim"' in setup
        assert "local_hour=07:00" in setup

    def test_setup_writes_the_draft_only_through_record_setup(self):
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        # The bug this guards: a session once hand-wrote .setup-draft.json
        # with a plain write_file call, then probed the printer and asked
        # about mail in that same reply, without the owner ever seeing the
        # printer question or the probe's answer ever landing in the
        # draft. record_setup.py is the only sanctioned writer now.
        assert "never a hand-edited" in setup
        assert "record_setup.py" in setup
        assert "NEXT_QUESTION" in setup
        for field in ("printer.configured", "mail.configured", "news_asked"):
            assert field in setup

    def test_soul_does_not_gate_the_hour_answer_behind_draft_none(self):
        # The bug this guards: the owner answered "7 is fine" while the
        # draft was still DRAFT:none (nothing had been recorded yet), and
        # SOUL.md's own DRAFT:none branch said "send the opener, stop" --
        # so the assistant re-sent the exact same hour question instead of
        # recording the answer it had just been given. SOUL.md must always
        # hand off to pt-setup (whose own step 1b recognizes an hour
        # answer) rather than deciding straight from DRAFT:none itself.
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "always load" in soul and "pt-setup" in soul
        assert "never decide" in soul.lower() or "not mean the incoming message" in soul

    def test_setup_distinguishes_a_probe_error_from_no_printer(self):
        # The bug this guards: lpstat -p came back exit_code=1 with
        # "lpstat: Bad file descriptor" -- a probe execution error, not a
        # real "no destinations" report -- and the assistant told the
        # owner "no printer was found" as if the check had actually run
        # cleanly. printer.configured still becomes false either way (never
        # guess true), but the two situations are not the same claim.
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert "Bad file descriptor" in setup
        assert "didn't run cleanly" in setup or "isn't a real lpstat report" in setup

    def test_setup_says_probe_outcomes_in_the_owners_language(self):
        # The bug this guards: after the printer probe, the assistant
        # replied in Portuguese even though the entire conversation (every
        # prior owner message) had been in English.
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert setup.count("owner's own language") >= 2


class TestUserStub:
    def test_runtime_user_md_forbids_a_profile_interview(self):
        text = (ROOT / "runtime" / "USER.md").read_text()
        assert "not a personal profile" in text.lower()
        assert "pt-setup" in text


class TestSkills:
    def test_every_pt_dir_carries_a_skill_manifest(self):
        for d in sorted(ROOT.glob("pt-*")):
            if not d.is_dir():
                continue
            skill = d / "SKILL.md"
            assert skill.is_file(), f"{d.name} has no SKILL.md"
            head = skill.read_text()
            assert head.startswith("---"), f"{d.name}/SKILL.md has no frontmatter"
            assert f"name: {d.name}" in head, f"{d.name}/SKILL.md frontmatter name mismatch"

    def test_setup_asks_about_the_priority_file(self):
        text = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert "NEXT_QUESTION=priority" in text
        assert "trying to make true" in text
        assert not (ROOT / "pt-setup" / "assets" / "prioritization.template.md").exists()
        section = text.split("## NEXT_QUESTION=priority", 1)[1].split("\n## ", 1)[0]
        assert "stays as it was" in section.lower()
        assert "leave it alone" not in section.lower()

    def test_no_skill_points_at_the_pre_wiki_homes(self):
        # The goals, the desk's Q&A and the owner's advisors moved into ~/Plow/wiki.
        # A skill still naming the old homes reads a file nothing writes any more.
        # pt/advisor.md is not stale: the desk's day page is still the container's.
        stale = (
            "~/Plow/prioritization.md",
            "priority.file",
            "~/Plow/advisors",
            "history.json",
            "history.py record",
        )
        skills = list(ROOT.glob("pt-*/**/*.md")) + [ROOT / "runtime" / "SOUL.md"]
        for skill in skills:
            if "assets/advisors" in str(skill):
                continue
            text = skill.read_text(encoding="utf-8")
            for old in stale:
                assert old not in text, f"{skill.relative_to(ROOT)} still names {old}"

    def test_priority_desk_is_documented_and_wired(self):
        desks = (ROOT / "pt-research" / "references" / "desks.md").read_text()
        assert "## Priority — first" in desks
        assert "Complete this desk before opening the shared browser" in desks
        assert "create the run's wiki state page" in desks
        assert "never proof that today's desk is complete" in desks
        assert "run/desk-calendar/events.json" in desks
        skill = (ROOT / "pt-priority" / "SKILL.md").read_text()
        assert "run/desk-priority/tournament.json" in skill
        assert "`name` = `imessage`" in skill
        assert "**An event is its people,**" in skill
        assert "never infer a stage" not in desks
        edition = (ROOT / "pt-edition" / "SKILL.md").read_text()
        assert "record_edition.py" in edition
        assert "Skipping this desk in the canonical scheduled paper is a bug" in desks
        # desks.md is the one statement of the priority rule (asserted in
        # test_priority_evolution_contract); pt-research owns the rosters.
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "gap card" not in soul
        assert "tournament" not in soul, "SOUL.md restates desks.md's priority rule"
        research = (ROOT / "pt-research" / "SKILL.md").read_text()
        assert "whose `deliver_at` is that hour" in research
        assert "the founder" in skill
        # The card's language is the owner's, read from config -- not inferred from this
        # file. A lone `você` exemplar was the only language signal the culler had, and it
        # wrote a Portuguese card for an English owner (#93).
        assert "Everything this desk writes" in skill
        # Free-form, not a flag: a binary en/pt branch silently gives a Mandarin owner
        # English text, and pt-edition promises "Mandarin in, Mandarin out".
        assert "a language to write in, never a flag to branch on" in skill
        assert "not a language inferred from this file" in skill
        assert "`you` in English, `você` in Portuguese" in skill
        assert "owner.language` from `/var/lib/hermes/pt/config.json`" in skill
        # A config with no owner.language must not send the culler back to inferring one;
        # pt-edition owns that fallback and this desk defers to it rather than forking it.
        assert "is `pt-edition/SKILL.md`'s case" in skill
        assert "Never omit the slot" in edition

    def test_soul_does_not_restate_delivery_argv(self):
        soul = (ROOT / "runtime" / "SOUL.md").read_text()
        assert "post_to_chat.py" not in soul

    def test_priority_evolution_contract(self):
        text = (ROOT / "pt-priority" / "SKILL.md").read_text()
        for clause in (
            "Mechanical loop (authoritative)",
            "Complete at least three generations",
            "six independent critic children in one delegate set",
            "A critic is a prosecutor, never a reviser",
            "exactly three grounded",
            "A recommendation without a supporting sourced quote is ineligible",
            "The three it returns quote three different sourced lines",
            "/var/lib/hermes/pt/run/desk-priority/tournament.candidate.json",
            "--tournament",
            "rewrite every reference to the owner by name or role into direct",
            "question in the owner's language -- the literal value read during Orient",
            "is a defect, not a style choice",
            "`RUN_PAGE=~/Plow/wiki/projects/theplowtimes/runs/<run-datetime>/state.md`",
            "sanitized `reads`",
            "reopens decisive public read receipts",
            "never contain raw private queries, selectors, URLs, or excerpts",
            "item (a re-open handle, not content)",
            "only after the renderer succeeds and `tournament.json` is atomically published",
        ):
            assert clause in text
        desks = (ROOT / "pt-research" / "references" / "desks.md").read_text()
        assert "reserved 150-minute window" in desks
        assert "reserved 150-minute window; delivery waits" in desks
        assert "ending earlier when the delivery cutoff requires it" not in desks
        assert "global batch budget starts after priority" in desks
        assert "One rule for every scheduled paper" in desks
        assert "never waits on a tournament" in desks and "`as_of`" in desks
        assert "accepted checkpoint" in desks and "reuse it" in desks
        assert "tournament.working.json" not in text + desks
        assert "newest active run page" not in text
        qa = (ROOT / "pt-shared" / "assets" / "wiki" / "qa.md").read_text()
        assert "Rank is positional" in qa
        assert "one adjacent position" in qa
        assert "current sourced facts" in qa
        assert "at most 1,200 characters" not in text

    def test_bundled_advisors_are_one_named_markdown_file_each(self):
        advisor_dir = ROOT / "pt-setup" / "assets" / "advisors"
        markdown = sorted(p.name for p in advisor_dir.glob("*.md") if p.name != "README.md")
        assert markdown == ["patrick-salyer.md"]
        assert not list(advisor_dir.glob("*-bank.json"))
        priority = (ROOT / "pt-priority" / "SKILL.md").read_text()
        assert "every `*.md` except `README.md`" in priority
        assert "salyer-*" not in priority and "salyer-bank.json" not in priority
        assert "owner advisor page" not in priority
        overview = (ROOT / "pt-shared" / "assets" / "wiki" / "overview.md").read_text()
        advisor_readme = (advisor_dir / "README.md").read_text()
        assert "Add your own advisor" not in overview
        assert "Owner-added advisors" not in advisor_readme
    def test_a_news_section_reads_back_what_it_printed(self):
        # A section researched with no memory of its own past editions prints
        # the same backgrounder every morning (issue #69). The instrument is
        # the advisor desk's, one level down -- not a second mechanism.
        research = (ROOT / "pt-research" / "SKILL.md").read_text()
        assert "history.py recent --topic" in research
        assert "already spent" in research
        shared = (ROOT / "pt-shared" / "SKILL.md").read_text()
        assert "--topic" in shared

    def test_a_claim_whose_item_will_not_reopen_is_unsupported(self):
        # A basis naming a file that does not exist kept its Answered standing
        # across three generations, because "missing access is unknown, never
        # disproved" is about the claim's truth and nothing spoke to its
        # standing (issues #72, #73).
        desk = (ROOT / "pt-priority" / "SKILL.md").read_text()
        assert "unsupported" in desk
        assert "re-open" in desk
        # the truth rule must survive untouched — the new rule is a different axis
        assert "unknown, never disproved" in desk
        # the rule needs an owner: only the live-read stages re-open what they stand on
        assert "the only stages with live read access — re-opens" in desk
        intake = (ROOT / "pt-intake" / "SKILL.md").read_text()
        assert "rowid" in intake and "confirm" in intake
        # a mail id alone is not an item -- ids from different mail readers aren't interchangeable
        assert "named mail reader" in intake

    def test_calendar_desk_uses_google_then_a_locked_applescript(self):
        # Measured live 2026-09-18: two real appointments, paper said the
        # day was empty. Google was called as `calendar today` (exit 2) and
        # `calendar list` (empty calendars, not events); Calendar.app was
        # queried while closed (-600) or with `time string of start date of
        # item 1 of every event` (-1700).
        desks = (ROOT / "pt-research" / "references" / "desks.md").read_text()
        script = (ROOT / "pt-research" / "assets" / "calendar.applescript").read_text()
        assert '["plow-gog", "calendar", "events", "--from", "today", "--days", "8",' in desks
        assert "unexpected argument today" in desks
        assert "calendar list" in desks
        assert "plow_run_applescript" in desks
        assert "assets/calendar.applescript" in desks
        assert "Nenhum evento hoje" in desks
        assert "failed or returned no event today" in desks
        assert '"attendees": []}' in desks
        assert "tell application \"Calendar\" to launch" in script
        assert "time string of start date of item 1" not in script
        assert "every event of item 1 of every calendar" not in script
        assert 'date "Friday' not in script
        assert "on error" not in script
        edition = (ROOT / "pt-edition" / "SKILL.md").read_text()
        assert "could not read the agenda" in edition

    def test_shared_helpers_exist_and_are_referenced(self):
        shared = ROOT / "pt-shared" / "scripts"
        for name in ("pt_config_gate.py", "post_to_chat.py", "bearer_http.py",
                     "run_lock.py", "setup_needed.py", "record_setup.py",
                     "record_owner_language.py",
                     "prepare_daily_run.py"):
            assert (shared / name).is_file(), f"pt-shared/scripts/{name} missing"

    def test_record_setup_is_executable_and_referenced(self):
        script = ROOT / "pt-shared" / "scripts" / "record_setup.py"
        assert script.stat().st_mode & stat.S_IXUSR, "record_setup.py must be executable"
        setup = (ROOT / "pt-setup" / "SKILL.md").read_text()
        assert (
            "/var/lib/hermes/skills/pt-shared/scripts/record_setup.py"
        ) in setup

    def test_edition_renderer_and_template_exist(self):
        edition = ROOT / "pt-edition"
        assert (edition / "scripts" / "render_edition.py").is_file()
        assert (edition / "template.html").is_file()

    def test_template_carries_no_script(self):
        # The Chrome-on-Mac PDF fallback executes JavaScript; the template
        # must stay inert, and the renderer is the only writer of markup.
        template = (ROOT / "pt-edition" / "template.html").read_text()
        assert "<script" not in template.lower()
        assert "onload=" not in template.lower()

    def test_template_keeps_every_slot_the_renderer_fills(self):
        # A restyle that drops a placeholder silently drops that desk from
        # the page. The renderer fills these; the template must keep them.
        template = (ROOT / "pt-edition" / "template.html").read_text()
        for slot in ("MASTHEAD", "DATE", "LOCATION", "LEAD", "PRIORITY_BLOCK",
                     "WEATHER_EAR", "NEWS_PAIR", "CALENDAR_RAIL"):
            assert "{{" + slot + "}}" in template, f"template lost {{{{{slot}}}}}"
        assert "{{SUDOKU}}" not in template

    def test_template_has_a_newspaper_front_page(self):
        # Measured live 2026-09-18: the page read as a newsletter, not a
        # newspaper. The reference is a broadsheet front page: nameplate,
        # a folio line, the lead as a large headline, and news in columns.
        template = (ROOT / "pt-edition" / "template.html").read_text()
        assert "nameplate" in template
        assert "inspired by Mayfield" in template
        assert "folio" in template
        assert "dropcap" in template
        assert "border-image" not in template  # no fake photo frames
        assert "masthead-row" in template
        assert "Every claim" not in template
        # The priority card's heading is model-written (owner.language),
        # not a hardcoded English/Portuguese string.
        assert "What should I prioritize today?" not in template
        assert "O que devo priorizar hoje?" not in template
        assert "PRIORITY_BLOCK" in template
        assert "kicker" in template
        assert "calendar-rail" in template
        assert "news-pair" in template
        assert "break-inside: avoid" in template
        # A long localized focus title must be a horizontal bar. Making it
        # a narrow table cell stacked the English title into five lines and
        # turned the card into a black vertical slab in the real PDF.
        assert ".section--priority > h2 {\n    display: block;" in template
        # Never display:none an element that gets a background from
        # another rule -- WeasyPrint 62.3 paints the background anyway
        # (measured: an empty black stripe where the "hidden" h2 was).
        assert "display: none" not in template

    def test_index_screenshots_are_shot_from_synthetic_fixture(self):
        # Agent Index thumbs used to be a live paper: the owner's city,
        # their priority file, and third-party inbox rows. Re-shoot from
        # index/edition.json (see index/render_screenshots.sh).
        fixture_path = ROOT / "index" / "edition.json"
        render = load_module("render_edition", "pt-edition/scripts/render_edition.py")
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert render.validate(fixture) == ""
        blob = json.dumps(fixture)
        for needle in (
            "Blumenau",
            "Delattre",
            "McDonald",
            "SW Blumenau",
            "$1-10M",
            "Blueprint",
        ):
            assert needle not in blob, needle
        jpg = ROOT / "index" / "edition-page-1.jpg"
        assert jpg.is_file() and jpg.stat().st_size > 0
        assert not (ROOT / "index" / "edition-page-2.jpg").exists()
        assert not (ROOT / "index" / "edition-page-3.jpg").exists()

    def test_recorder_has_only_the_current_recommendation_schema(self):
        recorder = (ROOT / "pt-edition" / "scripts" / "record_edition.py").read_text()
        assert "CARD_LINES" not in recorder
        assert 'card.get("why")' not in recorder

    def test_cross_skill_imports_resolve(self):
        # register_crons.py imports topics from pt-intake/scripts at run time;
        # both must be seeded side by side for that to work.
        assert (ROOT / "pt-intake" / "scripts" / "topics.py").is_file()
        assert (ROOT / "pt-dashboard" / "scripts" / "register_crons.py").is_file()


class TestDeployment:
    def test_skills_tsv_is_empty(self):
        # skills.tsv pins SHARED skills from other repos; this agent installs
        # no connectors -- Latch is the only mcp_server. Empty means exactly
        # that, and any row would be a credential-carrying dependency to review.
        content = (ROOT / "skills.tsv").read_text().strip()
        assert content == ""

    def test_config_declares_no_relay_server_of_its_own(self):
        config = (ROOT / "runtime" / "config.yaml").read_text()
        assert "plow-chat-platform" in config
        # plow-init manages the one relay entry in mcp_servers and enables it
        # exactly when the agent's identity carries a relay. A second entry
        # here hand-built a device URL from a static DOMO_* pair, and a stale
        # pair then won over the agent's own key and 401'd every run.
        assert "/v1/relay/devices/" not in config
        assert "DOMO_MCP_TOKEN" not in config and "DOMO_DEVICE_UID" not in config
        # Hard gate: Hermes web_extract / web_search / Playwright stay off.
        assert "disabled_toolsets" in config
        assert "\n    - web\n" in config
        assert "\n    - search\n" in config
        assert "\n    - browser\n" in config
        # Hard gate: plow_chat must not stream tool progress or mid-turn
        # assistant narration (Hermes default is both on for this platform).
        assert "interim_assistant_messages: false" in config
        assert 'tool_progress: "off"' in config
        assert "long_running_notifications: false" in config
        assert "default: anthropic/claude-opus-5" in config
        assert "anthropic/claude-opus-5: {}" in config

    def test_compose_yml_is_the_plow_agents_surface(self):
        # plow-agents' compose.example.yml: service `agent`, credential drop-in,
        # named home volume. compose.override.yml must not exist: Compose loads
        # that filename automatically and would start a second gateway.
        import re

        assert not (ROOT / "compose.override.yml").exists()
        text = (ROOT / "compose.yml").read_text()
        assert re.search(r"^  agent:", text, re.M)
        assert "build: ." in text
        assert "./plow-credentials:/var/lib/plow/credentials.host:ro" in text
        assert "agent-home:/var/lib/hermes" in text
        assert "AGENT_ID: theplowtimes" in text
        assert "TERMINAL_CWD" not in text
        assert "stop_grace_period: 35s" in text
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("-") and "skills" in stripped and "agent-home" not in stripped:
                raise AssertionError(f"skill mount in compose.yml: {stripped}")

    def test_compose_yml_does_not_pin_a_model(self):
        # Measured live: google/gemini-2.5-flash-lite never once called
        # skills_list/skill_view for a news request. Unpinned, provider/model
        # fall back to the Plow-hosted default, the same choice
        # life-assistant-hermes-agent's compose.yml makes by omission.
        text = (ROOT / "compose.yml").read_text()
        assert "HERMES_PROVIDER" not in text
        assert "HERMES_MODEL" not in text

    def test_dockerfile_copies_every_pt_skill_outside_the_home(self):
        import re

        dockerfile = (ROOT / "Dockerfile").read_text()
        skills = sorted(p.parent.name for p in ROOT.glob("pt-*/SKILL.md"))
        missing = [name for name in skills if f"COPY {name}/" not in dockerfile]
        assert missing == [], f"in the tree but never copied into the image: {', '.join(missing)}"
        for name in skills:
            assert re.search(
                rf"^COPY\s+{re.escape(name)}/\s+/opt/hermes/skills/{re.escape(name)}/\s*$",
                dockerfile,
                re.MULTILINE,
            ), f"COPY {name}/ does not land at /opt/hermes/skills/{name}/"
            assert f"/var/lib/hermes/skills/{name}" not in dockerfile
        assert "COPY runtime/SOUL.md /opt/hermes/plow-seed/SOUL.md" in dockerfile
        assert "COPY runtime/USER.md /var/lib/hermes/memories/USER.md" in dockerfile
        # The home's config is built from plow-seed; runtime/config.yaml is
        # merged onto it, and the home copy comes from that merge.
        assert "merge_pt_seed_config.py" in dockerfile
        assert "COPY runtime/config.yaml /var/lib/hermes" not in dockerfile
        assert "02-copy-plow-credentials" in dockerfile
        assert "plow-credentials" in (ROOT / ".dockerignore").read_text()
        assert "plow-credentials" in (ROOT / ".gitignore").read_text()

    def test_dockerfile_installs_weasyprint_for_the_pdf_leg(self):
        # The base image has no HTML-to-PDF engine; the renderer's --pdf leg
        # only works because this image installs weasyprint. The build's own
        # import check is the guard that it actually imports (native Pango/
        # Cairo binding fails at import, not at install).
        dockerfile = ROOT / "Dockerfile"
        assert dockerfile.is_file(), "Dockerfile installs weasyprint for the PDF leg"
        text = dockerfile.read_text()
        assert "weasyprint" in text
        assert "import weasyprint" in text
        # The build check must RENDER, not just import: a pydyf/weasyprint
        # mismatch imports clean and dies on the first write_pdf.
        assert "write_pdf" in text
        assert "pydyf" in text
        # Installed into BOTH interpreters, because which one `python3` means
        # depends on the shell, and this flow uses both:
        #   sh -c / bash -c -> /opt/hermes/.venv/bin/python3
        #   bash -lc        -> /usr/bin/python3   (login resets PATH, dropping
        #                                          /opt/hermes/.venv/bin)
        # History, in order, all measured live: a system dist-packages
        # `--target` made the LOGIN shell work and the plain shell fail, so
        # this test was written to forbid a login-shell probe. Then on
        # 2026-09-16 the venv-only install shipped and the agent's terminal
        # tool -- which runs a LOGIN shell -- got ModuleNotFoundError, was
        # told "weasyprint is not installed", took the text fallback, and
        # handed the owner a wall of text twice while the venv rendered that
        # same edition.json to a valid PDF. Neither interpreter alone is
        # enough; the answer is both, and a probe that proves both.
        assert "--python /opt/hermes/.venv/bin/python3" in text
        assert "--python /usr/bin/python3" in text
        assert text.count('"PyYAML==') == 2
        assert "import yaml" in text
        # The probe must exercise the plain shell AND the login shell: each
        # one alone has already shipped a broken PDF leg.
        assert "bash -lc" in text, "the build probe does not test a login shell"
        assert 'sh -c "python3 -c' in text, "the build probe does not test a plain shell"
        # Pinned by digest, like the fleet pin -- a tag re-resolves on pull.
        from_line = next(
            line for line in text.splitlines() if line.startswith("FROM ")
        )
        assert "@sha256:" in from_line



class TestImportability:
    def test_gate_imports_and_runs(self, tmp_path):
        gate = load_module("gate_contract", "pt-shared/scripts/pt_config_gate.py")
        path = tmp_path / "config.json"
        path.write_text('{"owner": {"timezone": "UTC"},'
                        ' "delivery": {"hour": "07:00"},'
                        ' "printer": {"configured": false}}')
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            gate.main([str(path)])
        assert buf.getvalue().strip() == ""
