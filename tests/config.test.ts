import assert from "node:assert/strict";
import { test } from "node:test";
import { renderConfig, type Identity } from "../boot/config.ts";

const identity: Identity = {
  agent: { name: "Juniper" },
  line: { uid: "ln_phone" },
  chats: [{ uid: "cht_home", status: "active", participants: [
    { type: "agent", relationship: "self", line: { uid: "ln_phone" } },
    { type: "member", role: "owner", uid: "mem_owner" },
  ] }],
};

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
  const config = renderConfig({ ...identity, chats: [...identity.chats,
    { uid: "cht_email", status: "active", participants: [
      { type: "agent", relationship: "self", line: { uid: "ln_mail", provider_type: "email" } },
      { type: "member", role: "owner", uid: "mem_owner" },
    ] },
    { ...identity.chats[0], uid: "cht_group", participants: [...identity.chats[0].participants,
      { type: "member", role: "member", uid: "mem_guest" },
    ] },
  ] }, "http://api:8000");
  assert.ok(!("ownerChatUid" in config.channels.plow));
  assert.equal(config.channels.plow.emailLineUid, "ln_mail");
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
  assert.equal(config.gateway.auth.token, "${OPENCLAW_GATEWAY_TOKEN}");
  assert.equal(config.mcp?.servers.plow.url, "http://127.0.0.1:18790/mcp");
  assert.equal(renderConfig(identity, "http://api:8000").mcp, undefined);
});

test("GLM 5.2 falls back to Sonnet, then Opus, on the Plow provider with explicit capacity and pricing", () => {
  const config = renderConfig(identity, "http://api:8000");
  assert.deepEqual(config.agents.defaults.model, {
    primary: "plow/z-ai/glm-5.2", fallbacks: ["plow/anthropic/claude-sonnet-5", "plow/anthropic/claude-opus-5"],
  });
  // contextWindow 262144: the Kimi K2.5 window in OpenClaw's own provider catalog
  // (moonshotai/kimi-k2.5); cost is what the Plow gateway billed on a measured call.
  assert.deepEqual(config.models.providers.plow.models, [{
    id: "moonshotai/kimi-k2.5", name: "Kimi K2.5", input: ["text"], contextWindow: 262144,
    // A reasoning model: without this OpenClaw drops its reasoning_content deltas, so a
    // long think looks idle (aborted at 120 s) and the next tool-call message is replayed
    // without the reasoning_content Kimi requires (measured live 2026-09-25).
    reasoning: true, maxTokens: 32768, compat: { requiresReasoningContentOnAssistantMessages: true },
    cost: { input: 0.57, output: 2.85 },
  }, {
    id: "z-ai/glm-5.2", name: "GLM 5.2", input: ["text"], contextWindow: 1048576,
    cost: { input: 0.5544, output: 1.7424 },
  }, {
    id: "anthropic/claude-opus-5", name: "Claude Opus 5", input: ["text", "image"], contextWindow: 1000000,
    contextTokens: 400_000, cost: { input: 5.00, output: 25.00 },
  }, {
    id: "anthropic/claude-sonnet-5", name: "Claude Sonnet 5", input: ["text", "image"], contextWindow: 1000000,
    cost: { input: 2.00, output: 10.00 },
  }]);
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
  } } });
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
    profile: "messaging", sessions: { visibility: "tree" }, alsoAllow: ["read", "write", "edit", "exec", "plow_start_thread", "plow_record_signal"], deny: ["ask_user", "secrets"],
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

test("the base image uses boot-owned config without the OpenClaw browser UI", () => {
  const config = renderConfig(identity, "http://api:8000");
  assert.equal(config.gateway.controlUi?.enabled, false);
  assert.equal(config.agents.defaults.skipBootstrap, true);
  assert.deepEqual(config.meta, {});
});

test("the Plow plugin may register its setup-gate prompt hook", () => {
  assert.deepEqual(renderConfig(identity, "http://api:8000").plugins, {
    load: { paths: ["/opt/plow/plugin"] },
    entries: { plow: { enabled: true, hooks: { allowConversationAccess: true } } },
  });
});
