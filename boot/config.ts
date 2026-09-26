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
        { id: "openai/gpt-6-luna", name: "GPT-6 Luna", input: ["text", "image"], contextWindow: 1050000,
          cost: { input: 0.10, output: 0.50 } },
      ],
    } } },
    agents: { entries: { main: { identity: { name } } }, defaults: {
      workspace: "/var/lib/plow/workspace", skipBootstrap: true,
      // The paper's AGENTS.md plus up to 8,000 characters of Latch instructions is
      // past OpenClaw's 20,000-character default; truncation drops its last rules.
      bootstrapMaxChars: 40_000,
      model: { primary: "plow/openai/gpt-6-luna", fallbacks: [] }, sandbox: { mode: "off" },
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
    // The channel runs the newspaper setup gate in a before_prompt_build hook; OpenClaw
    // registers conversation hooks of a non-bundled plugin only with this opt-in.
    plugins: { load: { paths: ["/opt/plow/plugin"] }, entries: { plow: { enabled: true, hooks: { allowConversationAccess: true } } } },
    channels: { plow: {
      apiBase, lineUid: identity.line.uid,
      // Groups are listen-only and anyone may join one, so in a group every
      // sender -- the owner too -- gets exactly one tool: recording a signal.
      // Any groups key turns on OpenClaw's group allowlist with mentions
      // required; "*" admits every group and the agent hears every message.
      groups: { "*": { requireMention: false, toolsBySender: { "*": { allow: ["plow_record_signal"] } } } },
      ...(email?.type === "agent" ? { emailLineUid: email.line.uid } : {}),
    } },
    session: { dmScope: "per-account-channel-peer", groupScope: "per-group" },
    bindings: [
      { agentId: "main", match: { channel: "plow", accountId: "chat", peer: { kind: "direct", id: "plow-owner" } }, session: { dmScope: "main" } },
      // Every group text gets its own session; the default per-group key is what
      // carries the group id OpenClaw resolves the group tool policy from.
      { agentId: "main", match: { channel: "plow", accountId: "chat", peer: { kind: "group", id: "*" } } },
    ],
    commands: { ownerAllowFrom: ["plow-owner"] },
    memory: { search: { rememberAcrossConversations: false } },
    // An empty allowlist means unrestricted in OpenClaw.
    skills: { load: { extraDirs: ["/opt/plow/skills"] }, allowBundled: ["plow-no-bundled-skills"] },
    // Keep workspace and durable memory writes local instead of routing them through the Mac relay.
    tools: {
      profile: "messaging", sessions: { visibility: "tree" }, alsoAllow: ["read", "write", "edit", "exec", "plow_start_thread", "plow_record_signal"], deny: ["ask_user", "secrets"],
      // The newspaper scripts' python3 is the image's 3.13 venv, never the system 3.11.
      exec: { pathPrepend: ["/opt/plow/pt-venv/bin"] },
    },
  };
}
