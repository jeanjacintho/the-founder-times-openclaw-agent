import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { test, type TestContext } from "node:test";
import JSON5 from "json5";
import { fileURLToPath } from "node:url";
import { renderConfig, syncConfig, type Identity } from "../boot/config.ts";
import { llmRoute } from "../boot/llm.ts";

const identity: Identity = {
  agent: { name: "Juniper" },
  line: { uid: "ln_phone" },
  chats: [{ uid: "cht_home", status: "active", participants: [
    { type: "agent", relationship: "self", line: { uid: "ln_phone" } },
    { type: "member", role: "owner", uid: "mem_owner" },
  ] }],
};

async function configFixture(t: TestContext) {
  const dir = await mkdtemp(join(tmpdir(), "plow-config-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return { path: join(dir, "openclaw.json"), includes: join(dir, "includes") };
}

test("only the owner's phone DM becomes main; other peers and groups stay isolated", () => {
  const config = renderConfig(identity, "http://api:8000");
  assert.ok(!("ownerChatUid" in config.channels.plow));
  assert.ok(!("ownerMemberUid" in config.channels.plow));
  assert.deepEqual(config.commands.ownerAllowFrom, ["plow-owner"]);
  assert.equal(config.session.dmScope, "per-account-channel-peer");
  assert.equal(config.session.groupScope, "per-group");
  assert.deepEqual(config.bindings[0], {
    agentId: "main", match: { channel: "plow", accountId: "chat", peer: { kind: "direct", id: "plow-owner" } },
    session: { dmScope: "main" },
  });
});

test("group chats get their own binding and only the signal tool, for everyone", () => {
  const config = renderConfig(identity, "http://api:8000");
  // No session override: the default per-group key carries the group id the
  // tool policy is resolved from, and the owner's exact DM binding stays first.
  assert.deepEqual(config.bindings[1], {
    agentId: "main", match: { channel: "plow", accountId: "chat", peer: { kind: "group", id: "*" } },
  });
  assert.deepEqual(config.bindings[0].match.peer, { kind: "direct", id: "plow-owner" });
  // Any groups key turns on OpenClaw's group allowlist with mentions required;
  // "*" admits every group and the agent must hear every message.
  assert.deepEqual(config.channels.plow.groups, { "*": {
    requireMention: false,
    toolsBySender: { "*": { allow: ["plow_record_signal"] } },
  } });
});

test("mailbox and group chats cannot displace the owner's DM", () => {
  const config = renderConfig({ ...identity, mailbox: { uid: "ln_mail", display_name: "Elm" }, chats: [...identity.chats,
    { uid: "cht_email", status: "active", participants: [
      { type: "agent", relationship: "self", line: { uid: "ln_mail" } },
      { type: "member", role: "owner", uid: "mem_owner" },
    ] },
    { ...identity.chats[0], uid: "cht_group", participants: [...identity.chats[0].participants,
      { type: "member", role: "member", uid: "mem_guest" },
    ] },
  ] }, "http://api:8000");
  assert.ok(!("ownerChatUid" in config.channels.plow));
  assert.equal(config.channels.plow.emailLineUid, "ln_mail");
});

test("the mailbox comes from identity, so it is served before its first thread exists", () => {
  assert.equal(renderConfig({ ...identity, mailbox: { uid: "ln_mail", display_name: "Elm" } }, "http://api:8000").channels.plow.emailLineUid, "ln_mail");
  assert.ok(!("emailLineUid" in renderConfig({ ...identity, mailbox: null }, "http://api:8000").channels.plow));
});

test("boot accepts no owner chat or ambiguous owner chats without waiting", () => {
  for (const chats of [[], [...identity.chats, ...identity.chats]]) {
    assert.deepEqual(renderConfig({ ...identity, chats }, "http://api:8000").commands.ownerAllowFrom, ["plow-owner"]);
  }
});

test("provider and optional MCP use environment references, never credential values", () => {
  const config = renderConfig({ ...identity, mcp_url: "http://api:8000/relay" }, "http://api:8000");
  assert.equal(config.models.providers.plow.apiKey, "${PLOW_AGENT_TOKEN}");
  assert.equal(config.models.providers.plow.baseUrl, "http://api:8000/v1");
  assert.equal(config.gateway.auth.mode, "trusted-proxy");
  assert.equal("password" in config.gateway.auth, false);
  assert.equal(config.mcp?.servers.plow.url, "http://127.0.0.1:18790/mcp");
  assert.deepEqual(renderConfig(identity, "http://api:8000").mcp, { sessionIdleTtlMs: 300_000 });
});

test("rendered config passes OpenClaw's config validate command", async t => {
  const dir = await mkdtemp(join(tmpdir(), "plow-openclaw-config-validate-"));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const configPath = join(dir, "openclaw.json");
  const config = renderConfig({ ...identity, mcp_url: "https://relay.internal/mcp" }, "http://api:8000");
  await writeFile(configPath, JSON.stringify(config));

  const openclawDist = dirname(fileURLToPath(import.meta.resolve("openclaw")));
  const cli = existsSync("/app/openclaw.mjs") ? "/app/openclaw.mjs" : join(dirname(openclawDist), "openclaw.mjs");
  const result = spawnSync(process.execPath, [cli, "config", "validate", "--json"], {
    encoding: "utf8",
    env: { ...process.env, OPENCLAW_CONFIG_PATH: configPath, OPENCLAW_STATE_DIR: dir },
  });
  assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
  assert.match(result.stdout, /"valid":\s*true/);
});

test("a one-click install runs on Plow's Sol, with Plow's Luna as its fallback", () => {
  const config = renderConfig(identity, "http://api:8000");
  assert.deepEqual(config.agents.defaults.model, {
    primary: "plow/openai/gpt-6-sol", fallbacks: ["plow/openai/gpt-6-luna"],
  });
  // Plow serves Sol with a 1,050,000-token window (The Plow Times #132); it
  // publishes no price for it, so the entry claims none.
  assert.deepEqual(config.models.providers.plow.models, [
    { id: "openai/gpt-6-sol", name: "GPT-6 Sol", input: ["text", "image"], contextWindow: 1050000 },
    { id: "openai/gpt-6-luna", name: "GPT-6 Luna", input: ["text", "image"], contextWindow: 1050000,
      cost: { input: 0.10, output: 0.50 } },
  ]);
  assert.equal("models" in config.agents.defaults, false, "Plow's route adds no per-model runtime policy");
  assert.equal("modelPolicy" in config.agents.defaults, false);
  assert.equal("utilityModel" in config.agents.defaults, false);
});

test("an OpenAI route falls back to Plow and runs on OpenClaw's own runtime", () => {
  const config = renderConfig(identity, "http://api:8000", llmRoute({}, "openai").route);
  assert.deepEqual(config.agents.defaults.model,
    { primary: "openai/gpt-6-sol", fallbacks: ["plow/openai/gpt-6-sol", "plow/openai/gpt-6-luna"] });
  assert.deepEqual(config.agents.defaults.models, { "openai/*": { agentRuntime: { id: "openclaw" } } });
  assert.deepEqual(config.agents.defaults.modelPolicy, { allow: [] });
  assert.equal(config.agents.defaults.utilityModel, "openai/gpt-6-sol");
  // Plow stays configured: it is the fallback, and the chat's own provider entry.
  assert.deepEqual(config.models.providers.plow.models.map(m => m.id), ["openai/gpt-6-sol", "openai/gpt-6-luna"]);
});

test("an OpenRouter route needs no runtime policy of its own", () => {
  const config = renderConfig(identity, "http://api:8000",
    llmRoute({ AGENT_PROVIDER: "openrouter", AGENT_MODEL: "openai/gpt-6-luna" }, undefined).route);
  assert.deepEqual(config.agents.defaults.model,
    { primary: "openrouter/openai/gpt-6-luna", fallbacks: ["plow/openai/gpt-6-sol", "plow/openai/gpt-6-luna"] });
  assert.equal("models" in config.agents.defaults, false);
});

test("the configured Plow provider permits an operator-controlled private endpoint", () => {
  const config = renderConfig(identity, "http://host.docker.internal:8080");
  assert.equal(config.models.providers.plow.request.allowPrivateNetwork, true);
});

test("MCP sessions share the loopback bridge and expire after five idle minutes", () => {
  const config = renderConfig({ ...identity, mcp_url: "https://relay.internal/mcp" }, "http://api:8000");
  assert.deepEqual(config.mcp, { sessionIdleTtlMs: 300_000, servers: { plow: {
    url: "http://127.0.0.1:18790/mcp", transport: "streamable-http",
    headers: { Authorization: "Bearer ${PLOW_MCP_BRIDGE_TOKEN}" }, requestTimeoutMs: 300_000,
    toolFilter: { include: ["plow_browser*", "plow_get_output", "plow_get_result", "plow_read_file", "plow_read_skill", "plow_run_applescript", "plow_run_command", "plow_write_file"] },
  } } });
});

test("the Plow MCP filter exposes only the Latch tools used by newspaper research", () => {
  const config = renderConfig({ ...identity, mcp_url: "https://relay.internal/mcp" }, "http://api:8000");
  assert.deepEqual(config.mcp?.servers?.plow?.toolFilter?.include, [
    "plow_browser*", "plow_get_output", "plow_get_result", "plow_read_file", "plow_read_skill",
    "plow_run_applescript", "plow_run_command", "plow_write_file",
  ]);
  assert.deepEqual(config.tools.alsoAllow.filter(name => name.startsWith("plow__")), [
    "plow__plow_browser*", "plow__plow_get_output", "plow__plow_get_result", "plow__plow_read_file",
    "plow__plow_read_skill", "plow__plow_run_applescript", "plow__plow_run_command", "plow__plow_write_file",
  ]);
  assert.ok(config.tools.alsoAllow.includes("process"), "OpenClaw 2026.9.6 no longer infers process from exec");
  assert.ok(!config.tools.alsoAllow.includes("group:plugins"), "do not grant every plugin tool");
});

test("the advisor tournament can run six leaf sub-agents without chat turns preferring delegation", () => {
  assert.deepEqual(renderConfig(identity, "http://api:8000").agents.defaults.subagents, {
    maxChildrenPerAgent: 6, maxConcurrent: 6, maxSpawnDepth: 1, delegationMode: "suggest",
  });
});

test("phone turns cannot block on ask_user or read secrets", () => {
  assert.deepEqual(renderConfig(identity, "http://api:8000").tools.deny, ["ask_user", "secrets"]);
});

test("native messaging retains local workspace and memory file tools", () => {
  assert.deepEqual(renderConfig(identity, "http://api:8000").tools, {
    message: { crossContext: { allowWithinProvider: false, allowAcrossProviders: false } },
    profile: "messaging", toolSearch: false, codeMode: { enabled: false }, sessions: { visibility: "tree" }, alsoAllow: [
      "read", "write", "edit", "exec", "process", "plow_start_thread", "plow_record_signal",
      "plow_set_thread_trust", "plow_reply_to", "plow_send_email",
      "plow__plow_browser*", "plow__plow_get_output", "plow__plow_get_result", "plow__plow_read_file",
      "plow__plow_read_skill", "plow__plow_run_applescript", "plow__plow_run_command", "plow__plow_write_file",
    ], deny: ["ask_user", "secrets"],
    exec: { pathPrepend: ["/opt/plow/pt-venv/bin"] },
  });
});

test("exec resolves python3 to the newspaper venv", () => {
  assert.deepEqual(renderConfig(identity, "http://api:8000").tools.exec, { pathPrepend: ["/opt/plow/pt-venv/bin"] });
});

test("private transcript recall is disabled across isolated conversations", () => {
  assert.equal(renderConfig(identity, "http://api:8000").memory.search.rememberAcrossConversations, false);
});


test("the API agent name configures the assistant identity", () => {
  const config = renderConfig(identity, "http://api:8000");
  assert.deepEqual(config.agents.entries, { main: { identity: { name: "Juniper" } } });
});

for (const name of [undefined, null, "", "  "]) test(`missing agent name is not invented: ${JSON.stringify(name)}`, () => {
  assert.throws(() => renderConfig({ ...identity, agent: { name } }, "http://api:8000"), /no usable agent.name/);
});

test("the base image uses boot-owned config with the OpenClaw browser UI", () => {
  const config = renderConfig(identity, "http://api:8000");
  assert.equal(config.gateway.controlUi.enabled, true);
  assert.equal(config.agents.defaults.skipBootstrap, true);
  assert.deepEqual(config.messages, { visibleReplies: "automatic", queue: { mode: "collect" } });
  assert.deepEqual(config.meta, {});
});

test("the Plow plugin may register its setup-gate prompt hook", () => {
  assert.deepEqual(renderConfig(identity, "http://api:8000").plugins, {
    load: { paths: ["/opt/plow/plugin"] },
    entries: { plow: { enabled: true, hooks: { allowConversationAccess: true } } },
  });
});

test("boot renders the group trust mode into the owned channel config", () => {
  for (const mode of ["ask", "trusted", "untrusted"]) {
    assert.equal(renderConfig(identity, "http://api:8000", undefined, mode).channels.plow.threadTrust, mode);
  }
  assert.throws(() => renderConfig(identity, "http://api:8000", undefined, "invalid"), /PLOW_THREAD_TRUST/);
});

test("the dashboard uses the proxy's port and accepts origins checked by the proxy", () => {
  const config = renderConfig(identity, "http://api:8000");
  assert.deepEqual(config.gateway, {
    mode: "local", bind: "loopback", port: 3000,
    controlUi: { enabled: true, allowedOrigins: ["*"] },
    auth: { mode: "trusted-proxy", trustedProxy: {
      userHeader: "x-plow-user", allowLoopback: true,
      deviceAutoApprove: { enabled: true, scopes: ["operator.admin"] },
    } },
    trustedProxies: ["127.0.0.1"],
    reload: { mode: "off" },
  });
});

test("fresh boot seeds owner defaults and external includes for Plow-owned settings", async t => {
  const { path, includes } = await configFixture(t);
  await syncConfig(renderConfig(identity, "http://api:8000"), path, includes);
  const owner = JSON5.parse(await readFile(path, "utf8"));
  assert.deepEqual(owner.meta, {});
  assert.deepEqual(owner.agents.defaults, { $include: join(includes, "agent-defaults.json5") });
  assert.equal(JSON5.parse(await readFile(join(includes, "agent-defaults.json5"), "utf8")).model.primary, "plow/openai/gpt-6-sol");
  assert.deepEqual(owner.skills, { $include: join(includes, "skills.json5") });
  assert.equal(JSON5.parse(await readFile(join(includes, "skills.json5"), "utf8")).load.extraDirs[0], "/opt/plow/skills");
  assert.deepEqual(owner.gateway, { $include: join(includes, "gateway.json5") });
  assert.equal(JSON5.parse(await readFile(join(includes, "plow-channel.json5"), "utf8")).threadTrust, "ask");
  assert.deepEqual(owner.messages.visibleReplies, { $include: join(includes, "visible-replies.json5") });
  assert.equal(JSON5.parse(await readFile(join(includes, "visible-replies.json5"), "utf8")), "automatic");
  assert.equal(owner.bindings.length, 2);
  assert.deepEqual(owner.bindings[0], { $include: join(includes, "binding.json5") });
  assert.deepEqual(owner.bindings[1].match.peer, { kind: "group", id: "*" });
  assert.deepEqual(JSON5.parse(await readFile(join(includes, "gateway.json5"), "utf8")).port, 3000);
});

test("restart migrates a full render and keeps owner edits outside Plow-owned paths", async t => {
  const { path, includes } = await configFixture(t);
  const old = renderConfig(identity, "http://old-api:8000") as Record<string, any>;
  old.channels.telegram = { enabled: true };
  old.models.providers.extra = { baseUrl: "https://example.com" };
  old.plugins.entries.extra = { enabled: true };
  old.agents.defaults.model.primary = "extra/model";
  old.agents.entries.main.identity.emoji = "old";
  old.messages.queue = { mode: "steer", cap: 99 };
  old.messages.groupChat = { visibleReplies: "message_tool" };
  old.bindings.unshift({ agentId: "extra", match: { channel: "telegram" } });
  await writeFile(path, `// owner settings\n${JSON.stringify(old)}\n`);
  await syncConfig(renderConfig(identity, "http://new-api:8000"), path, includes);
  const owner = JSON5.parse(await readFile(path, "utf8"));
  assert.deepEqual(owner.channels.telegram, { enabled: true });
  assert.deepEqual(owner.models.providers.extra, { baseUrl: "https://example.com" });
  assert.deepEqual(owner.plugins.entries.extra, { enabled: true });
  // The paper owns its model: an owner edit there does not survive a restart.
  assert.deepEqual(owner.agents.defaults, { $include: join(includes, "agent-defaults.json5") });
  assert.deepEqual(JSON5.parse(await readFile(join(includes, "message-queue.json5"), "utf8")), { mode: "collect" });
  assert.deepEqual(owner.messages.groupChat, { visibleReplies: "message_tool" });
  assert.deepEqual(owner.agents.entries.main.identity, { $include: join(includes, "identity.json5") });
  assert.equal(owner.bindings.length, 3);
  assert.deepEqual(owner.bindings[0], { $include: join(includes, "binding.json5") });
  assert.deepEqual(owner.bindings[1], { agentId: "extra", match: { channel: "telegram" } });
  assert.deepEqual(owner.bindings[2].match.peer, { kind: "group", id: "*" });
  assert.equal(JSON5.parse(await readFile(join(includes, "plow-provider.json5"), "utf8")).baseUrl, "http://new-api:8000/v1");
  owner.gateway.port = 9999;
  owner.channels.plow.enabled = false;
  await writeFile(path, JSON.stringify(owner));
  await syncConfig(renderConfig(identity, "http://newer-api:8000"), path, includes);
  const again = JSON5.parse(await readFile(path, "utf8"));
  assert.deepEqual(again.gateway, { $include: join(includes, "gateway.json5") });
  assert.deepEqual(again.channels.plow, { $include: join(includes, "plow-channel.json5") });
  assert.deepEqual(again.channels.telegram, { enabled: true });
  assert.equal(again.bindings.length, 3);
  assert.deepEqual(again.messages.groupChat, { visibleReplies: "message_tool" });
});

test("MCP Plow server include disappears without a relay while owner MCP settings remain", async t => {
  const { path, includes } = await configFixture(t);
  await syncConfig(renderConfig({ ...identity, mcp_url: "https://relay.example" }, "http://api:8000"), path, includes);
  const owner = JSON5.parse(await readFile(path, "utf8"));
  owner.mcp.servers.other = { url: "https://other.example" };
  await writeFile(path, JSON.stringify(owner));
  await syncConfig(renderConfig(identity, "http://api:8000"), path, includes);
  const again = JSON5.parse(await readFile(path, "utf8"));
  assert.equal(again.mcp.servers.plow, undefined);
  assert.deepEqual(again.mcp.servers.other, { url: "https://other.example" });
  assert.equal(again.mcp.sessionIdleTtlMs, 300_000);
});
