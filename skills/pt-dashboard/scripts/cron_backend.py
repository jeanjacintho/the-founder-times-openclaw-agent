"""The schedule register_crons.py writes to: OpenClaw's own scheduler.

Every call is `node /app/openclaw.mjs cron ...` against the gateway this
turn runs in -- exec inherits OPENCLAW_GATEWAY_TOKEN from it, so no token is
ever an argument. Jobs are agent turns in an isolated session with delivery
`none`: the paper reaches chat through post_to_chat.py, never the runner's
announce. Cron jobs carry the owner's zone (`--tz`), so the schedule is the
owner's wall clock with no conversion; one-shots take an ISO time with its
offset (`--at`).

What this module guarantees, measured against OpenClaw 2026.9.4:

  * `cron list` hides disabled jobs, so listing always passes `--all` -- a
    disabled (paused) pt-* job must be seen, or it is re-created beside itself.
  * The listing is paginated (`hasMore`). A partial listing is not an answer.
  * Never read "I could not tell what is registered" as "nothing is": a
    failed command, non-JSON, a wrong shape or a truncated page ABORTS.
  * OpenClaw's own jobs (heartbeat, memory dreaming, skill review) live in the
    same list; callers only ever act on pt-* names.
"""
from __future__ import annotations

import json
import subprocess

OPENCLAW = ["node", "/app/openclaw.mjs"]
MODEL = "plow/anthropic/claude-opus-5"


class Job(dict):
    """One registered automation, as `cron list --json` returns it."""

    @property
    def id(self):
        return self["id"]

    @property
    def name(self):
        return self["name"]

    @property
    def enabled(self):
        return bool(self.get("enabled"))

    @property
    def spec(self):
        """The fields drift is judged on; None where OpenClaw did not say."""
        schedule = self.get("schedule") or {}
        payload = self.get("payload") or {}
        expr = schedule.get("expr") if schedule.get("kind") == "cron" else schedule.get("at")
        return {"schedule": expr, "tz": schedule.get("tz"),
                "prompt": payload.get("message"), "model": payload.get("model")}


def _run(argv):
    return subprocess.run(argv, capture_output=True, text=True)


def _refuse(what, proc=None, detail=""):
    tail = f":\n{proc.stdout}\n{proc.stderr}" if proc is not None else f" ({detail})"
    raise SystemExit(f"refusing to register: {what}{tail}")


class CronBackend:
    def __init__(self, runner=_run):
        self.runner = runner

    def _cron(self, *args):
        return [*OPENCLAW, "cron", *args]

    def list(self):
        """Every registered automation, enabled or not. Aborts on any doubt."""
        proc = self.runner(self._cron("list", "--all", "--json"))
        if proc.returncode != 0:
            _refuse("could not list the scheduler's jobs", proc)
        try:
            listing = json.loads(proc.stdout)
            rows = listing["jobs"]
        except (ValueError, KeyError, TypeError) as exc:
            _refuse("the scheduler's job listing is not the expected JSON", detail=repr(exc))
        if not isinstance(rows, list) or not all(isinstance(r, dict) and "id" in r and "name" in r for r in rows):
            _refuse("the scheduler's job listing has an unexpected shape", detail=repr(rows)[:200])
        if listing.get("hasMore"):
            _refuse("the scheduler's job listing is truncated (hasMore)", detail=f"total={listing.get('total')}")
        return [Job(r) for r in rows]

    def _schedule_args(self, job):
        if job.get("tz"):
            return ["--cron", job["schedule"], "--tz", job["tz"], "--exact"]
        return ["--at", job["schedule"]]

    def create_argv(self, job):
        return self._cron("add", "--name", job["name"], *self._schedule_args(job),
                          "--session", "isolated", "--message", job["prompt"],
                          "--no-deliver", "--model", job.get("model", MODEL), "--json")

    def edit_argv(self, job_id, job):
        """Patch a registered job in place -- never remove-then-create, or a
        failed create leaves the paper with no job."""
        return self._cron("edit", job_id, *self._schedule_args(job),
                          "--message", job["prompt"], "--no-deliver",
                          "--model", job.get("model", MODEL), "--json")

    def remove_argv(self, job_id):
        return self._cron("rm", job_id, "--json")

    def create(self, job):
        return self.runner(self.create_argv(job))

    def edit(self, job_id, job):
        return self.runner(self.edit_argv(job_id, job))

    def remove(self, job_id):
        return self.runner(self.remove_argv(job_id))
