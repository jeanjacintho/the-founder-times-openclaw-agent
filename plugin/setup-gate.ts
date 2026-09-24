import { execFile } from "node:child_process";
import type { Chat } from "./transport.ts";

// The newspaper's first-run gate, run by the channel before the owner's own
// DM turn so the model starts from its answer instead of having to remember
// to ask. The prompt keeps "run the gate first" as the fallback: nothing is
// injected when the gate cannot run, and the model then runs it itself.
// PT_SKILLS and PT_HOME override the image paths, as they do for pt_paths.py.
export const gateScript = () => `${process.env.PT_SKILLS || "/opt/plow/skills"}/pt-shared/scripts/setup_needed.py`;
export const gateConfig = () => `${process.env.PT_HOME || "/var/lib/plow/pt"}/config.json`;
const VENV_BIN = "/opt/plow/pt-venv/bin";

export type GateRunner = (file: string, args: string[], env: NodeJS.ProcessEnv) => Promise<string>;

const runScript: GateRunner = (file, args, env) => new Promise((resolve, reject) => {
  execFile(file, args, { env, timeout: 10_000, maxBuffer: 16_384 }, (error, stdout) => error ? reject(error) : resolve(stdout));
});

// Only the owner's solo DM gets setup: groups and other people's DMs answer
// what was asked and ask none of setup's questions.
export function isOwnerDm(chat: Chat, lineUid: string): boolean {
  return chat.participants.length === 2 &&
    chat.participants.some(p => p.type === "agent" && p.relationship === "self" && p.line.uid === lineUid) &&
    chat.participants.some(p => p.type === "member" && p.role === "owner");
}

// SETUP_NEEDED + DRAFT: + LANG:, or READY + LANG:. Anything else is not the
// gate's answer and must not be passed off as one.
export function parseGate(stdout: string): string | undefined {
  const lines = stdout.trim().split("\n").map(line => line.trim());
  const valid = lines[0] === "SETUP_NEEDED"
    ? lines.length === 3 && lines[1].startsWith("DRAFT:") && lines[2].startsWith("LANG:")
    : lines[0] === "READY" && lines.length === 2 && lines[1].startsWith("LANG:");
  return valid ? lines.join("\n") : undefined;
}

export async function runGate(run: GateRunner = runScript): Promise<string | undefined> {
  try {
    const env = { ...process.env, PATH: `${VENV_BIN}:${process.env.PATH ?? ""}` };
    return parseGate(await run(gateScript(), [gateConfig()], env));
  } catch {
    return undefined;
  }
}

export function gateContext(output: string): string {
  return [
    "Newspaper setup gate, already run by the Plow channel for this turn:",
    "```text", output, "```",
    `This is the output of \`${gateScript()} ${gateConfig()}\`: your first action for this turn is done; do not run it again.`,
  ].join("\n");
}
