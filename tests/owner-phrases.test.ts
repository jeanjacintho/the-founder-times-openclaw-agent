import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { test } from "node:test";
import { EDITION_FAILED, editionFailedNotice } from "../plugin/owner-phrases.ts";

async function home(t: { after: (fn: () => unknown) => void }, language: string | undefined, phrases?: { language: string; phrases: Record<string, string> }, draft?: string) {
  const dir = await mkdtemp(`${tmpdir()}/pt-home-`);
  if (language !== undefined) await writeFile(`${dir}/config.json`, JSON.stringify({ owner: { timezone: "UTC", language } }));
  if (draft) await writeFile(`${dir}/.setup-draft.json`, JSON.stringify({ owner: { language: draft } }));
  if (phrases) await writeFile(`${dir}/owner-phrases.json`, JSON.stringify(phrases));
  process.env.PT_HOME = dir;
  t.after(async () => { delete process.env.PT_HOME; await rm(dir, { recursive: true }); });
}

const zh = { language: "Mandarin Chinese", phrases: { "edition.failed": "版本未送达，因为必要的运行步骤失败了。" } };

for (const [label, language, phrases, draft, expected] of [
  ["no config at all", undefined, undefined, undefined, EDITION_FAILED.en],
  ["English", "English", undefined, undefined, EDITION_FAILED.en],
  ["Portuguese, curated", "Português", undefined, undefined, EDITION_FAILED.pt],
  ["pt-BR tag", "pt-BR", undefined, undefined, EDITION_FAILED.pt],
  ["a written language", "Mandarin Chinese", zh, undefined, zh.phrases["edition.failed"]],
  ["phrases written for another language", "Deutsch", zh, undefined, EDITION_FAILED.en],
  ["an unwritten language", "Mandarin Chinese", undefined, undefined, EDITION_FAILED.en],
  ["the setup draft's language wins", "English", undefined, "Português", EDITION_FAILED.pt],
] as const) test(`the failed-edition notice speaks the owner's language: ${label}`, async t => {
  await home(t, language, phrases, draft);
  assert.equal(await editionFailedNotice(), expected);
});
