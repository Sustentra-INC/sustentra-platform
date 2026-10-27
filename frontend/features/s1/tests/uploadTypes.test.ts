import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { isReadableUpload, READABLE_UPLOAD_EXTENSIONS, READABLE_UPLOAD_TYPES } from "../constants/uploads";

// The upload dialog sets aside what the upload route would refuse, so its lists must be the
// route's: the parser's routes (backend/app/services/parser_service.py), with images narrowed
// to what the readers open (backend/app/api/documents.py). Read from the backend's source, so
// a format added on one side and not the other fails here.
const backend = (...path: string[]) => readFileSync(join(process.cwd(), "..", "backend", "app", ...path), "utf8");
const parserService = backend("services", "parser_service.py");
const documentsApi = backend("api", "documents.py");

/** The quoted strings of a Python set or frozenset assigned to `name`. */
function pythonSet(source: string, name: string): string[] {
  const match = new RegExp(`^${name} = (?:frozenset\\()?\\{([^}]*)\\}`, "m").exec(source);
  if (!match) throw new Error(`${name} not found`);
  return [...match[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

/** The quoted keys of a Python dict literal assigned to `name`. */
function pythonDictKeys(source: string, name: string): string[] {
  const match = new RegExp(`^${name} = \\{([^}]*)\\}`, "m").exec(source);
  if (!match) throw new Error(`${name} not found`);
  return [...match[1].matchAll(/"([^"]+)":/g)].map((m) => m[1]);
}

describe("readable uploads: the frontend's lists match the backend's", () => {
  it("accepts exactly the extensions the upload route accepts", () => {
    const routed = [...parserService.matchAll(/^([A-Z_]+_EXTENSIONS) = /gm)].map((m) => m[1]);
    expect(routed).toContain("IMAGE_EXTENSIONS");
    const documents = routed.filter((name) => name !== "IMAGE_EXTENSIONS").flatMap((name) => pythonSet(parserService, name));
    const images = pythonSet(documentsApi, "UPLOAD_IMAGE_EXTENSIONS");

    expect([...READABLE_UPLOAD_EXTENSIONS].sort()).toEqual([...documents, ...images].sort());
  });

  it("accepts exactly the media types the upload route accepts", () => {
    const routed = pythonDictKeys(parserService, "MIME_TYPE_ROUTES");
    const images = pythonSet(documentsApi, "UPLOAD_IMAGE_TYPES");

    expect([...READABLE_UPLOAD_TYPES].sort()).toEqual([...routed, ...images].sort());
    // A file with no extension is judged by its media type alone, as in the route.
    for (const type of [...routed, ...images]) expect(isReadableUpload({ name: "upload", type })).toBe(true);
  });
});
