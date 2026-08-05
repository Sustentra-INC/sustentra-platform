import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { resolveFieldKey } from "../utils/resolveFieldKey";

describe("field resolver", () => {
  it("renders backend identifiers as an opaque provisional key", () => {
    expect(
      resolveFieldKey({
        canonicalTypeId: "CT-S2-ELECBILL",
        backendFieldId: "consumption_kwh",
      })
    ).toBe("CT-S2-ELECBILL::consumption_kwh");
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
