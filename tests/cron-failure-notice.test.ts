import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { notifyFailedPaperRun } from "../plugin/cron-failure-notice.ts";

test("a UUID paper cron ending NO_REPLY sends one owner notice, even on success", async t => {
  const home = await mkdtemp(join(tmpdir(), "pt-cron-notice-"));
  await writeFile(join(home, "config.json"), JSON.stringify({ owner: { language: "Português" } }));
  const previous = { PT_HOME: process.env.PT_HOME, PLOW_API_BASE: process.env.PLOW_API_BASE,
    PLOW_HOME_CHANNEL: process.env.PLOW_HOME_CHANNEL, PLOW_AGENT_TOKEN: process.env.PLOW_AGENT_TOKEN };
  process.env.PT_HOME = home;
  process.env.PLOW_API_BASE = "https://plow.example/";
  process.env.PLOW_HOME_CHANNEL = "cht_owner";
  process.env.PLOW_AGENT_TOKEN = "fixture-token";
  t.after(async () => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    await rm(home, { recursive: true, force: true });
  });

  const sent: { url: string; body: string }[] = [];
  t.mock.method(globalThis, "fetch", async (url: string | URL | Request, init?: RequestInit) => {
    sent.push({ url: String(url), body: String(init?.body) });
    return Response.json({ uid: "notice" });
  });
  const jobId = "234701df-102e-46e0-9126-19944320159d";
  const event = { runId: "run-paper-no-delivery", success: true, messages: [
    { role: "user", content: [{ type: "text", text: `[cron:${jobId} pt-daily-edition-now] Run the daily edition now.` }] },
    { role: "assistant", content: [{ type: "text", text: "NO_REPLY" }] },
  ] };
  const context = { jobId };
  await notifyFailedPaperRun(event, context);
  await notifyFailedPaperRun(event, context);

  assert.equal(sent.length, 1);
  assert.equal(sent[0].url, "https://plow.example/v1/chats/cht_owner/messages");
  assert.equal(JSON.parse(sent[0].body).body, "A edição não foi entregue porque uma etapa necessária da execução falhou.");
});

test("confirmed delivery and non-paper crons do not send failure notices", async t => {
  t.mock.method(globalThis, "fetch", async () => { throw new Error("must not send"); });
  const heartbeatId = "7b427468-6565-4d61-9be1-21a3d4176f2b";
  await notifyFailedPaperRun({ runId: "run-paper-ok", success: true, messages: [{
    role: "tool", content: [{ type: "text", text: "chat edition posted (text)" }],
  }, {
    role: "user", content: [{ type: "text", text: "[cron:paper-id pt-daily-edition] Run the daily edition." }],
  }] }, { jobId: "paper-id" });
  await notifyFailedPaperRun({ runId: "run-heartbeat", success: false, messages: [
    { role: "user", content: [{ type: "text", text: `[cron:${heartbeatId} heartbeat-main] Check in.` }] },
  ] }, { jobId: heartbeatId });
  await notifyFailedPaperRun({ runId: "run-mismatched-envelope", success: true, messages: [
    { role: "user", content: [{ type: "text", text: "[cron:another-id pt-daily-edition] Run the daily edition." }] },
    { role: "assistant", content: [{ type: "text", text: "NO_REPLY" }] },
  ] }, { jobId: "mismatched-id" });
  await notifyFailedPaperRun({ runId: "run-posted", success: false, messages: [{
    role: "tool_result", content: [{ type: "text", text: "chat edition posted (pdf) /var/lib/plow/pt/run/paper.pdf" }],
  }, {
    role: "user", content: [{ type: "text", text: "[cron:posted-id pt-daily-edition] Run the daily edition." }],
  }] }, { jobId: "posted-id" });
});

test("a run that already messaged the owner does not send a second notice", async t => {
  t.mock.method(globalThis, "fetch", async () => { throw new Error("must not send"); });
  const jobId = "55555555-5555-4555-8555-555555555555";
  await notifyFailedPaperRun({ runId: "run-owner-already-notified", success: true, messages: [
    { role: "user", content: [{ type: "text", text: `[cron:${jobId} pt-oneoff-topic1] Run the topic.` }] },
    {
      role: "assistant", content: [{ type: "tool_use", name: "message", input: {
        action: "send", channel: "plow", accountId: "chat", to: "plow-owner", message: "The edition was not delivered.",
      } }],
  }] }, { jobId });
});

test("paper job names in the real cron envelope include numbered daily editions", async t => {
  const home = await mkdtemp(join(tmpdir(), "pt-cron-notice-"));
  await writeFile(join(home, "config.json"), JSON.stringify({ owner: { language: "Português" } }));
  const previous = { PT_HOME: process.env.PT_HOME, PLOW_API_BASE: process.env.PLOW_API_BASE,
    PLOW_HOME_CHANNEL: process.env.PLOW_HOME_CHANNEL, PLOW_AGENT_TOKEN: process.env.PLOW_AGENT_TOKEN };
  process.env.PT_HOME = home;
  process.env.PLOW_API_BASE = "https://plow.example";
  process.env.PLOW_HOME_CHANNEL = "cht_owner";
  process.env.PLOW_AGENT_TOKEN = "fixture-token";
  t.after(async () => {
    for (const [key, value] of Object.entries(previous)) {
      if (value === undefined) delete process.env[key]; else process.env[key] = value;
    }
    await rm(home, { recursive: true, force: true });
  });

  const sent: string[] = [];
  t.mock.method(globalThis, "fetch", async (url: string | URL | Request) => {
    sent.push(String(url));
    return Response.json({ uid: "notice" });
  });
  const jobId = "c98f042a-6834-4a56-a5f0-e4306a4540bd";
  await notifyFailedPaperRun({ runId: "run-extra-paper", success: true, messages: [
    { role: "user", content: [{ type: "text", text: `[cron:${jobId} pt-daily-edition-2] Run the daily edition.` }] },
    { role: "assistant", content: [{ type: "text", text: "NO_REPLY" }] },
  ] }, { jobId });
  assert.equal(sent.length, 1);
});

test("a run that stopped on a spent day does not repeat the failure notice", async t => {
  t.mock.method(globalThis, "fetch", async () => { throw new Error("must not send"); });
  const jobId = "9a1f1c1a-0b8f-4c52-8e0b-5f0b4a7f2d11";
  await notifyFailedPaperRun({ runId: "run-spent-day", success: true, messages: [
    { role: "user", content: [{ type: "text", text: `[cron:${jobId} pt-daily-edition-now] Run the daily edition. On 'give-up-quiet' release the lock and stop.` }] },
    { role: "tool", content: [{ type: "text", text: "give-up-quiet\n" }] },
    { role: "assistant", content: [{ type: "text", text: "NO_REPLY" }] },
  ] }, { jobId });
});
