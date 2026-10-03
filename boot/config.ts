import { mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";
import JSON5 from "json5";
import { PLOW_ROUTE, type LlmRoute } from "./llm.ts";

export type Participant =
  | { type: "member"; uid: string; role: string }
  | { type: "agent"; relationship: string; line: { uid: string } };
export type Identity = {
  agent?: { name?: string | null; web_url?: string | null };
  line: { uid: string };
  mailbox?: { uid: string; display_name: string } | null;
  chats: { uid: string; status: string; participants: Participant[] }[];
  mcp_url?: string | null;
};

export function renderConfig(identity: Identity, apiBase: string, llm: LlmRoute = PLOW_ROUTE, threadTrust = process.env.PLOW_THREAD_TRUST ?? "ask") {
  if (threadTrust !== "ask" && threadTrust !== "trusted" && threadTrust !== "untrusted") {
    throw new Error("PLOW_THREAD_TRUST must be ask, trusted, or untrusted");
  }
  const name = identity.agent?.name;
  if (typeof name !== "string" || !name.trim()) throw new Error(`Identity has no usable agent.name: ${JSON.stringify(name)}`);
  return {
    meta: {},
    gateway: {
      mode: "local", bind: "loopback", port: 3000, controlUi: { enabled: true, allowedOrigins: ["*"] },
      auth: { mode: "trusted-proxy", trustedProxy: {
        userHeader: "x-plow-user", allowLoopback: true,
        deviceAutoApprove: { enabled: true, scopes: ["operator.admin"] },
      } },
      trustedProxies: ["127.0.0.1"],
      reload: { mode: "off" },
    },
    models: { providers: { plow: {
      baseUrl: `${apiBase}/v1`, apiKey: "${PLOW_AGENT_TOKEN}", api: "openai-completions", authHeader: true,
      request: { allowPrivateNetwork: true },
      // Plow serves Sol with a 1,050,000-token window and publishes no price for it.
      models: [
        { id: "openai/gpt-6-sol", name: "GPT-6 Sol", input: ["text", "image"], contextWindow: 1050000 },
        { id: "openai/gpt-6-luna", name: "GPT-6 Luna", input: ["text", "image"], contextWindow: 1050000,
          cost: { input: 0.10, output: 0.50 } },
      ],
    } } },
    agents: { entries: { main: { identity: { name } } }, defaults: {
      workspace: "/var/lib/plow/workspace", skipBootstrap: true,
      // The paper's AGENTS.md plus up to 8,000 characters of Latch instructions is
      // past OpenClaw's 20,000-character default; truncation drops its last rules.
      bootstrapMaxChars: 40_000,
      model: { primary: llm.primary, fallbacks: llm.fallbacks }, sandbox: { mode: "off" },
      // Off Plow, titles and recaps use the chosen model too: OpenAI's own
      // small-model default is a model the owner did not pick.
      ...(llm.provider === "plow" ? {} : { utilityModel: llm.primary }),
      // Signed in with the owner's own account, an openai/* model may otherwise
      // run on the native Codex harness, which skips this plugin's hooks and the
      // per-sender tool policy. The empty allow list keeps the entry from reading
      // as a legacy model restriction, so Plow's fallback stays selectable.
      ...(llm.provider === "openai" ? {
        models: { "openai/*": { agentRuntime: { id: "openclaw" } } }, modelPolicy: { allow: [] },
      } : {}),
      // The advisor tournament spawns up to six critics at once; children never spawn.
      // Delegation stays a suggestion so owner chat turns are not pushed into sub-agents.
      subagents: { maxChildrenPerAgent: 6, maxConcurrent: 6, maxSpawnDepth: 1, delegationMode: "suggest" },
    } },
    mcp: { sessionIdleTtlMs: 300_000, ...(identity.mcp_url ? { servers: { plow: {
      url: "http://127.0.0.1:18790/mcp", transport: "streamable-http",
      // Browser reads and plow_get_result waits on the Mac outlast the 60s default.
      requestTimeoutMs: 300_000,
      // Keep the newspaper's Latch surface explicit. MCP tools are filtered by
      // server-local names before the session tool profile is applied.
      toolFilter: { include: [
        "plow_browser*", "plow_get_output", "plow_get_result", "plow_read_file",
        "plow_read_skill", "plow_run_applescript", "plow_run_command", "plow_write_file",
      ] },
      headers: { Authorization: "Bearer ${PLOW_MCP_BRIDGE_TOKEN}" },
    } } } : {}) },
    // The channel runs the newspaper setup gate in a before_prompt_build hook; OpenClaw
    // registers conversation hooks of a non-bundled plugin only with this opt-in.
    plugins: { load: { paths: ["/opt/plow/plugin"] }, entries: { plow: { enabled: true, hooks: { allowConversationAccess: true } } } },
    messages: { visibleReplies: "automatic", queue: { mode: "collect" } },
    channels: { plow: {
      apiBase, lineUid: identity.line.uid, threadTrust,
      // Groups are listen-only and anyone may join one, so in a group every
      // sender -- the owner too -- gets exactly one tool: recording a signal.
      // Any groups key turns on OpenClaw's group allowlist with mentions
      // required; "*" admits every group and the agent hears every message.
      groups: { "*": { requireMention: false, toolsBySender: { "*": { allow: ["plow_record_signal"] } } } },
      ...(identity.mailbox ? { emailLineUid: identity.mailbox.uid, emailName: identity.mailbox.display_name } : {}),
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
      message: { crossContext: { allowWithinProvider: false, allowAcrossProviders: false } },
      // Keep configured research tools visible as direct model tools. OpenClaw
      // Code Mode catalogs every eligible tool behind exec/wait and has no
      // per-tool visibility allowlist.
      profile: "messaging", toolSearch: false, codeMode: { enabled: false }, sessions: { visibility: "tree" }, alsoAllow: [
        "read", "write", "edit", "exec", "process", "plow_start_thread", "plow_record_signal",
        "plow_set_thread_trust", "plow_reply_to", "plow_send_email",
        "plow__plow_browser*", "plow__plow_get_output", "plow__plow_get_result", "plow__plow_read_file",
        "plow__plow_read_skill", "plow__plow_run_applescript", "plow__plow_run_command", "plow__plow_write_file",
      ], deny: ["ask_user", "secrets"],
      // The newspaper scripts' python3 is the image's 3.13 venv, never the system 3.11.
      exec: { pathPrepend: ["/opt/plow/pt-venv/bin"] },
    },
  };
}

const ownedPaths = [
  ["gateway", ["gateway"]],
  ["plow-provider", ["models", "providers", "plow"]],
  ["plow-mcp", ["mcp", "servers", "plow"]],
  ["plow-channel", ["channels", "plow"]],
  ["plow-plugin", ["plugins", "entries", "plow"]],
  ["plugin-load", ["plugins", "load"]],
  ["tools", ["tools"]],
  ["commands", ["commands"]],
  ["visible-replies", ["messages", "visibleReplies"]],
  ["message-queue", ["messages", "queue"]],
  ["identity", ["agents", "entries", "main", "identity"]],
  // The paper's model, bootstrap budget and advisor sub-agents, and the skills
  // it runs, ship with the image: an owner edit here would break the edition.
  ["agent-defaults", ["agents", "defaults"]],
  ["skills", ["skills"]],
  ["session", ["session"]],
  ["memory", ["memory"]],
] as const;

type ConfigObject = Record<string, unknown>;

function isObject(value: unknown): value is ConfigObject {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function getPath(root: ConfigObject, path: readonly string[]): unknown {
  let node: unknown = root;
  for (const key of path) node = isObject(node) ? node[key] : undefined;
  return node;
}

function parentAt(root: ConfigObject, path: readonly string[], create: boolean): ConfigObject | undefined {
  let node = root;
  for (const key of path.slice(0, -1)) {
    let next = node[key];
    if (!isObject(next)) {
      if (!create) return undefined;
      next = {};
      node[key] = next;
    }
    node = next as ConfigObject;
  }
  return node;
}

function isPlowOwnerBinding(value: unknown): boolean {
  if (!isObject(value) || !isObject(value.match)) return false;
  const match = value.match;
  return value.agentId === "main" && match.channel === "plow" && match.accountId === "chat"
    && isObject(match.peer) && match.peer.kind === "direct" && match.peer.id === "plow-owner";
}

export async function syncConfig(
  rendered: ReturnType<typeof renderConfig>, configPath: string, includeDir: string,
): Promise<void> {
  const seed = rendered as unknown as ConfigObject;
  await mkdir(includeDir, { recursive: true });
  let owner: ConfigObject;
  try {
    const parsed: unknown = JSON5.parse(await readFile(configPath, "utf8"));
    if (!isObject(parsed)) throw new Error("openclaw.json must contain an object");
    owner = parsed;
  } catch (error) {
    if (!(error instanceof Error && "code" in error && error.code === "ENOENT")) throw error;
    owner = structuredClone(seed);
  }

  for (const [file, path] of ownedPaths) {
    const value = getPath(seed, path);
    const parent = parentAt(owner, path, value !== undefined);
    if (!parent) continue;
    const key = path.at(-1)!;
    const includePath = join(includeDir, `${file}.json5`);
    if (value === undefined) {
      delete parent[key];
      await rm(includePath, { force: true });
    } else {
      await writeFile(includePath, JSON.stringify(value, null, 2) + "\n");
      parent[key] = { $include: includePath };
    }
  }
  const bindingPath = join(includeDir, "binding.json5");
  await writeFile(bindingPath, JSON.stringify(rendered.bindings[0], null, 2) + "\n");
  const ownerBindings = Array.isArray(owner.bindings) ? owner.bindings.filter(binding =>
    !(isObject(binding) && binding.$include === bindingPath) && !isPlowOwnerBinding(binding)) : [];
  owner.bindings = [{ $include: bindingPath }, ...ownerBindings];
  const temporaryPath = `${configPath}.tmp`;
  await writeFile(temporaryPath, JSON.stringify(owner, null, 2) + "\n", { mode: 0o600 });
  await rename(temporaryPath, configPath);
}
