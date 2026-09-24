import type { Identity } from "./config.ts";

// The newspaper scripts run through exec, which inherits the gateway's
// environment. They reach the owner's Mac at PLOW_MCP_URL and post to the
// owner's DM at PLOW_HOME_CHANNEL. The owner's DM is the one the Plow channel
// treats as the owner (findOwnerChat): active, exactly this line and an owner.
// Blank when unknown, never stale; owner_chat.py asks Plow again at use.
export function newspaperEnv(identity: Identity): { PLOW_MCP_URL: string; PLOW_HOME_CHANNEL: string } {
  const owners = identity.chats.filter(chat => chat.status === "active" && chat.participants.length === 2 &&
    chat.participants.some(p => p.type === "agent" && p.relationship === "self" && p.line.uid === identity.line.uid) &&
    chat.participants.some(p => p.type === "member" && p.role === "owner"));
  return {
    PLOW_MCP_URL: identity.mcp_url ?? "",
    PLOW_HOME_CHANNEL: owners.length === 1 ? owners[0].uid : "",
  };
}
