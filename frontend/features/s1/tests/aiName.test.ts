import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { AI_FACILITY, AI_TYPE, AI_VALUE } from "../constants/copy";

// Users see "Sustentra's AI", never the vendor's model name.
const ROOT = join(__dirname, "..");

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "tests" ? [] : sources(path);
    return /\.(ts|tsx)$/.test(name) ? [path] : [];
  });
}

const withoutComments = (text: string) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");

describe("the AI is called Sustentra's AI on screen", () => {
  it("has no 'Claude' in the copy constants", () => {
    const all = [
      AI_TYPE.suggested, AI_TYPE.disagreesOn("Gas bill", "Water bill"), AI_FACILITY.suggested,
      ...Object.values(AI_VALUE).map((v) => (typeof v === "function" ? v(3) : v)),
    ];
    for (const text of all) expect(text).not.toMatch(/claude/i);
  });

  it("has no 'Claude' in any string or JSX text of the S1 sources", () => {
    const offenders: string[] = [];
    for (const file of sources(ROOT)) {
      withoutComments(readFileSync(file, "utf8")).split("\n").forEach((line, i) => {
        if (/\bClaude\b/.test(line)) offenders.push(`${file.slice(ROOT.length)}:${i + 1}: ${line.trim()}`);
      });
    }
    expect(offenders).toEqual([]);
  });
});
