import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { resolveFieldKey } from "../utils/resolveFieldKey";

describe("field resolver", () => {
  it("uses backend candidate identity as the stable opaque provisional key", () => {
    expect(
      resolveFieldKey({
        candidateId: "cand-123",
        documentId: "DOC-0001",
        backendFieldId: "consumption_kwh",
      })
    ).toBe("candidate:cand-123");
  });

  it("does not derive fallback keys from canonical document type", () => {
    expect(
      resolveFieldKey({
        documentId: "DOC-0001",
        backendFieldId: "consumption_kwh",
      })
    ).toBe("field:DOC-0001::consumption_kwh");
  });

  it("keeps raw field_id text out of active S1 implementation files", () => {
    const root = join(process.cwd(), "features", "s1");
    const hits = listFiles(root)
      .filter((file) => !file.includes(`${join("features", "s1", "docs")}`))
      .filter((file) => !file.includes(`${join("features", "s1", "tests")}`))
      .filter((file) => !file.endsWith("README.md"))
      .flatMap((file) => {
        const text = readFileSync(file, "utf8");
        return text.includes("field_id") ? [file] : [];
      });

    expect(hits).toEqual([]);
  });
});

function listFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    return statSync(path).isDirectory() ? listFiles(path) : [path];
  });
}
