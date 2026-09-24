export type Participant =
  | { type: "member"; uid: string; role: string }
  | { type: "agent"; relationship: string; line: { uid: string; provider_type?: string } };
export type Identity = {
  agent?: { name?: string | null };
  line: { uid: string };
  chats: { uid: string; status: string; participants: Participant[] }[];
  mcp_url?: string | null;
};

export function renderConfig(identity: Identity, apiBase: string) {
  const name = identity.agent?.name;
  if (typeof name !== "string" || !name.trim()) throw new Error(`Identity has no usable agent.name: ${JSON.stringify(name)}`);
  const email = identity.chats.flatMap(chat => chat.participants).find(p =>
    p.type === "agent" && p.relationship === "self" && p.line.provider_type === "email");
  return {
    meta: {},
    gateway: { mode: "local", bind: "loopback", controlUi: { enabled: false }, auth: { mode: "token", token: "${OPENCLAW_GATEWAY_TOKEN}" }, reload: { mode: "off" } },
    models: { providers: { plow: {
      baseUrl: `${apiBase}/v1`, apiKey: "${PLOW_AGENT_TOKEN}", api: "openai-completions", authHeader: true,
      request: { allowPrivateNetwork: true },
      models: [
        // The paper was tuned on Opus 5; other models wrote shorter, worse editions.
        // contextTokens is the working budget OpenClaw compacts against: 400k leaves
        // a three-generation advisor tournament room without compaction churn.
        { id: "anthropic/claude-opus-5", name: "Claude Opus 5", input: ["text", "image"], contextWindow: 1000000, contextTokens: 400_000, cost: { input: 5.00, output: 25.00 } },
        { id: "anthropic/claude-sonnet-5", name: "Claude Sonnet 5", input: ["text", "image"], contextWindow: 1000000, cost: { input: 2.00, output: 10.00 } },
      ],
    } } },
    agents: { entries: { main: { identity: { name } } }, defaults: {
      workspace: "/var/lib/plow/workspace", skipBootstrap: true,
      // The paper's AGENTS.md plus up to 8,000 characters of Latch instructions is
      // past OpenClaw's 20,000-character default; truncation drops its last rules.
      bootstrapMaxChars: 40_000,
      model: { primary: "plow/anthropic/claude-opus-5", fallbacks: ["plow/anthropic/claude-sonnet-5"] }, sandbox: { mode: "off" },
      // The advisor tournament spawns up to six critics at once; children never spawn.
      // Delegation stays a suggestion so owner chat turns are not pushed into sub-agents.
      subagents: { maxChildrenPerAgent: 6, maxConcurrent: 6, maxSpawnDepth: 1, delegationMode: "suggest" },
    } },
    ...(identity.mcp_url ? { mcp: { sessionIdleTtlMs: 300_000, servers: { plow: {
      url: "http://127.0.0.1:18790/mcp", transport: "streamable-http",
      // Browser reads and plow_get_result waits on the Mac outlast the 60s default.
      requestTimeoutMs: 300_000,
      headers: { Authorization: "Bearer ${PLOW_MCP_BRIDGE_TOKEN}" },
    } } } } : {}),
    plugins: { load: { paths: ["/opt/plow/plugin"] }, entries: { plow: { enabled: true } } },
    channels: { plow: {
      apiBase, lineUid: identity.line.uid,
      ...(email?.type === "agent" ? { emailLineUid: email.line.uid } : {}),
    } },
    session: { dmScope: "per-account-channel-peer", groupScope: "per-group" },
    bindings: [{ agentId: "main", match: { channel: "plow", accountId: "chat", peer: { kind: "direct", id: "plow-owner" } }, session: { dmScope: "main" } }],
    commands: { ownerAllowFrom: ["plow-owner"] },
    memory: { search: { rememberAcrossConversations: false } },
    // An empty allowlist means unrestricted in OpenClaw.
    skills: { load: { extraDirs: ["/opt/plow/skills"] }, allowBundled: ["plow-no-bundled-skills"] },
    // Keep workspace and durable memory writes local instead of routing them through the Mac relay.
    tools: {
      profile: "messaging", sessions: { visibility: "tree" }, alsoAllow: ["read", "write", "edit", "exec", "plow_start_thread"], deny: ["ask_user", "secrets"],
      // The newspaper scripts' python3 is the image's 3.13 venv, never the system 3.11.
      exec: { pathPrepend: ["/opt/plow/pt-venv/bin"] },
    },
  };
}
