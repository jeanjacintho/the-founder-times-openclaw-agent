import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { test } from "node:test";
import entry from "../plugin/index.ts";
import { gateContext, isOwnerDm, isOwnerDmTurn, parseGate, runGate } from "../plugin/setup-gate.ts";
import { websocketFixture } from "./ws-fixture.ts";

const self = { type: "agent" as const, relationship: "self", line: { uid: "line" } };
const owner = { type: "member" as const, uid: "owner", role: "owner", display_name: "Owner", provider_key: "+15550000001" };
const guest = { type: "member" as const, uid: "guest", role: "member", display_name: "Guest", provider_key: "+15550000003" };

test("only the gate's own two shapes are passed on", () => {
  assert.equal(parseGate("SETUP_NEEDED\nDRAFT:none\nLANG:unrecorded\n"), "SETUP_NEEDED\nDRAFT:none\nLANG:unrecorded");
  assert.equal(parseGate("READY\nLANG:Português\n"), "READY\nLANG:Português");
  for (const garbage of ["", "READY", "SETUP_NEEDED\nLANG:x", "Traceback (most recent call last):", "READY\nLANG:x\nextra"]) {
    assert.equal(parseGate(garbage), undefined, garbage);
  }
});

test("the gate runs with the venv first on PATH and a failure injects nothing", async () => {
  let seen: { file: string; args: string[]; path?: string } | undefined;
  assert.equal(await runGate(async (file, args, env) => { seen = { file, args, path: env.PATH }; return "READY\nLANG:English\n"; }), "READY\nLANG:English");
  assert.equal(seen!.file, "/opt/plow/skills/pt-shared/scripts/setup_needed.py");
  assert.deepEqual(seen!.args, ["/var/lib/plow/pt/config.json"]);
  assert.ok(seen!.path!.startsWith("/opt/plow/pt-venv/bin:"));
  assert.equal(await runGate(async () => { throw new Error("ENOENT"); }), undefined);
});

test("setup belongs to the owner's solo DM only", () => {
  const chat = (...participants: object[]) => ({ uid: "c", status: "active", trusted: false, participants }) as never;
  assert.equal(isOwnerDm(chat(self, owner), "line"), true);
  assert.equal(isOwnerDm(chat(self, owner, guest), "line"), false);
  assert.equal(isOwnerDm(chat(self, guest), "line"), false);
  assert.equal(isOwnerDm(chat({ ...self, line: { uid: "mailbox" } }, owner), "line"), false);
});

test("the injected context says the first action is done", () => {
  const text = gateContext("READY\nLANG:English");
  assert.match(text, /READY\nLANG:English/);
  assert.match(text, /do not run it again/);
});

for (const room of ["owner-dm", "group"] as const) test(`an inbound ${room} turn ${room === "owner-dm" ? "starts from the real gate" : "listens instead of the gate"}`, async t => {
  const home = await mkdtemp(`${tmpdir()}/pt-home-`);
  t.after(() => rm(home, { recursive: true }));
  await writeFile(`${home}/config.json`, JSON.stringify({ owner: { timezone: "UTC", language: "English" }, delivery: { hour: "07:00" }, printer: { configured: false } }));
  process.env.PT_HOME = home;
  process.env.PT_SKILLS = new URL("../skills", import.meta.url).pathname;
  t.after(() => { delete process.env.PT_HOME; delete process.env.PT_SKILLS; });

  const { server, apiBase, abortAfter } = await websocketFixture(t);
  const controller = abortAfter();
  const account = { apiBase, accountId: "chat", lineUid: "line" };
  const chat = { uid: "chat", status: "active", trusted: false, participants: room === "owner-dm" ? [owner, self] : [owner, guest, self] };
  t.mock.method(globalThis, "fetch", async (url: string) => Response.json(
    url.endsWith("/chats") ? { data: [chat], has_more: false } : url.endsWith("/chats/chat") ? chat :
    url.includes("/messages?") ? { data: [], has_more: false } : { ticket: "ticket", uid: "reply" }));
  server.on("connection", (socket: { send: (text: string) => void }) => socket.send(JSON.stringify({ event_type: "message_received", event_id: "event", chat_id: "chat", data: { message: { uid: "inbound", direction: "inbound", sender: owner, body: "oi", attachments: [], created_at: new Date().toISOString() } } })));

  let hook: (() => Promise<{ prependContext?: string } | undefined>) | undefined;
  let injected: { prependContext?: string } | undefined | "not-called" = "not-called";
  let channel: { gateway: { startAccount: (context: object) => Promise<void> } } | undefined;
  entry.register({ registrationMode: "full", registerTool() {}, logger: { info() {} },
    on(name: string, handler: typeof hook) { if (name === "before_prompt_build") hook = handler; },
    registerChannel(value: { plugin: typeof channel }) { channel = value.plugin; },
    runtime: { channel: {
      routing: { resolveAgentRoute: () => ({ sessionKey: "main" }) },
      inbound: { buildContext: async () => ({}), dispatch: async (dispatch: { replyOptions: { onAgentRunTerminalOutcome: (o: string) => void } }) => {
        injected = await hook!();
        dispatch.replyOptions.onAgentRunTerminalOutcome("completed");
        controller.abort();
        return { dispatched: true, dispatchResult: { deliberateSilentTerminalReply: true } };
      } },
    } },
  } as never);
  assert.ok(hook, "the plugin registers a before_prompt_build hook");
  await channel!.gateway.startAccount({ account, cfg: {}, abortSignal: controller.signal, log: { info() {} } });
  if (room === "owner-dm") {
    assert.ok(injected && injected !== "not-called");
    assert.match(injected.prependContext!, /```text\nREADY\nLANG:English\n```/);
  } else {
    // A group never gets setup; it gets the listen-only instructions.
    assert.ok(injected && injected !== "not-called");
    assert.match(injected.prependContext!, /GROUP LISTENING/);
    assert.doesNotMatch(injected.prependContext!, /READY/);
  }
});

test("the hook recognizes the owner's DM turn from its own context", () => {
  const owner = { channel: "plow", accountId: "chat", sessionKey: "agent:main:main", trigger: "user" };
  assert.equal(isOwnerDmTurn(owner), true);
  assert.equal(isOwnerDmTurn({ ...owner, trigger: undefined }), true);
  assert.equal(isOwnerDmTurn({ ...owner, accountId: undefined }), true);
  assert.equal(isOwnerDmTurn({ ...owner, trigger: "heartbeat" }), false);
  assert.equal(isOwnerDmTurn({ ...owner, trigger: "cron" }), false);
  assert.equal(isOwnerDmTurn({ ...owner, sessionKey: "agent:main:plow:group:cht_group" }), false);
  assert.equal(isOwnerDmTurn({ ...owner, accountId: "email" }), false);
  assert.equal(isOwnerDmTurn({ ...owner, channel: undefined }), false);
  assert.equal(isOwnerDmTurn(undefined), false);
});

// Live, the gateway runs the agent turn from its ingress queue, outside the
// channel's dispatch: the hook sees only its own context.
for (const [label, ctx, injects] of [
  ["owner's DM", { channel: "plow", accountId: "chat", sessionKey: "agent:main:main", trigger: "user" }, true],
  ["heartbeat in the main session", { channel: "plow", accountId: "chat", sessionKey: "agent:main:main", trigger: "heartbeat" }, false],
  ["a group", { channel: "plow", accountId: "chat", sessionKey: "agent:main:plow:group:cht_group", trigger: "user" }, "listen"],
  ["a scheduled job", { sessionKey: "cron:pt-daily-edition", trigger: "cron" }, false],
] as const) test(`outside dispatch, ${label} ${injects === "listen" ? "listens instead of" : injects ? "starts from" : "skips"} the real gate`, async t => {
  const home = await mkdtemp(`${tmpdir()}/pt-home-`);
  t.after(() => rm(home, { recursive: true }));
  await writeFile(`${home}/config.json`, JSON.stringify({ owner: { timezone: "UTC", language: "English" }, delivery: { hour: "07:00" }, printer: { configured: false } }));
  process.env.PT_HOME = home;
  process.env.PT_SKILLS = new URL("../skills", import.meta.url).pathname;
  t.after(() => { delete process.env.PT_HOME; delete process.env.PT_SKILLS; });
  let hook: ((event: object, ctx: object) => Promise<{ prependContext?: string } | undefined>) | undefined;
  entry.register({ registrationMode: "full", registerTool() {}, logger: { info() {} }, registerChannel() {}, runtime: {},
    on(name: string, handler: typeof hook) { if (name === "before_prompt_build") hook = handler; } } as never);
  const result = await hook!({ prompt: "oi", messages: [] }, ctx);
  if (injects === "listen") {
    assert.match(result!.prependContext!, /GROUP LISTENING/);
    assert.doesNotMatch(result!.prependContext!, /READY/);
  } else if (injects) assert.match(result!.prependContext!, /```text\nREADY\nLANG:English\n```/);
  else assert.equal(result, undefined);
});
