import { readFile } from "node:fs/promises";

// The fixed line the channel writes itself: the notice for a paper run that
// failed. Its words come from the same place as every script's fixed line: the
// owner's own language when the paper has written its phrases, curated
// Portuguese or English otherwise.
export const EDITION_FAILED = {
  en: "The edition was not delivered because a required run step failed.",
  pt: "A edição não foi entregue porque uma etapa necessária da execução falhou.",
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

export async function editionFailedNotice(): Promise<string> {
  const language = await ownerLanguage();
  const stored = await readJson(`${ptHome()}/owner-phrases.json`) as { language?: unknown; phrases?: Record<string, unknown> } | undefined;
  const written = stored?.phrases?.["edition.failed"];
  if (language && stored?.language === language && typeof written === "string" && written.trim()) return written;
  return isPortuguese(language) ? EDITION_FAILED.pt : EDITION_FAILED.en;
}
