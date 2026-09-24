import { readFile } from "node:fs/promises";

// The one fixed line the channel writes itself: the notice after a turn that
// could not finish. Its words come from the same place as every script's fixed
// line (skills/pt-shared/scripts/owner_phrases.py): the owner's own language
// when the paper has written its phrases, curated Portuguese or English
// otherwise. The curated texts must match owner_phrases.py (a contract test
// holds them together).
export const TURN_FAILED = {
  en: "I couldn't finish handling your last message. Part of the request may have already happened, so please check before resending.",
  pt: "Não consegui terminar de tratar sua última mensagem. Parte do pedido pode já ter acontecido — confira antes de mandar de novo.",
};

const ptHome = () => process.env.PT_HOME || "/var/lib/plow/pt";

async function readJson(path: string): Promise<unknown> {
  try { return JSON.parse(await readFile(path, "utf8")); } catch { return undefined; }
}

function languageOf(data: unknown): string {
  const language = (data as { owner?: { language?: unknown } } | undefined)?.owner?.language;
  return typeof language === "string" ? language.trim() : "";
}

// The recorded language: the setup draft first, then the config (as setup_needed.py reads it).
export async function ownerLanguage(): Promise<string> {
  return languageOf(await readJson(`${ptHome()}/.setup-draft.json`)) || languageOf(await readJson(`${ptHome()}/config.json`));
}

export function isPortuguese(language: string): boolean {
  const tag = language.toLowerCase().replaceAll("_", "-");
  return tag.includes("portug") || tag === "pt" || tag.startsWith("pt-");
}

export async function turnFailedNotice(): Promise<string> {
  const language = await ownerLanguage();
  const stored = await readJson(`${ptHome()}/owner-phrases.json`) as { language?: unknown; phrases?: Record<string, unknown> } | undefined;
  const written = stored?.phrases?.["turn.failed"];
  if (language && stored?.language === language && typeof written === "string" && written.trim()) return written;
  return isPortuguese(language) ? TURN_FAILED.pt : TURN_FAILED.en;
}
