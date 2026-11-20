/* @vitest-environment jsdom */
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import type { EvidenceActivityItem, EvidenceTree, FolderAnswer } from "../api/evidenceTree";
import { ApiError } from "../../../lib/api";
import { demoApi } from "../demo-backend";
import { demoDecisions, setDemoEngagement } from "../demo-backend/state";
import { engagementConfig } from "../fixtures/engagementConfig";

const ID = engagementConfig.engagementId;
const folders = `/engagements/${ID}/evidence-folders`;
const BLOCK_1 = "block:summary";

beforeAll(() => {
  vi.stubEnv("NEXT_PUBLIC_S1_DATA_MODE", "fixture");
  setDemoEngagement({ ...engagementConfig, evidenceLines: [], evidenceFolders: [] });
});
afterAll(() => {
  vi.unstubAllEnvs();
});

const refused = async (promise: Promise<unknown>): Promise<ApiError> => {
  try {
    await promise;
  } catch (error) {
    return error as ApiError;
  }
  throw new Error("expected the request to be refused");
};
const tree = () => demoApi<EvidenceTree>(`/engagements/${ID}/evidence-tree`);
const inFolder = (id: string, doc: string, folderId: string | null) =>
  demoApi<{ payload: { folderId?: string } }>(`/engagements/${ID}/documents/${doc}/folder`, { method: "POST", body: { folder_id: folderId } });

describe("demo backend: Block 1 folders", () => {
  it("creates and renames folders with non-ASCII names, refuses bad names and duplicates, and logs both", async () => {
    const created = await demoApi<FolderAnswer>(folders, { method: "POST", body: { name: "  Données   de l’année 排放 🌱 " } });
    expect(created.folder?.name).toBe("Données de l’année 排放 🌱");
    expect((await refused(demoApi(folders, { method: "POST", body: { name: "   " } }))).status).toBe(422);
    expect((await refused(demoApi(folders, { method: "POST", body: { name: "a\u0000b" } }))).status).toBe(422);
    expect((await refused(demoApi(folders, { method: "POST", body: { name: "x".repeat(121) } }))).status).toBe(422);
    await demoApi(folders, { method: "POST", body: { name: "Café" } });
    expect((await refused(demoApi(folders, { method: "POST", body: { name: "CAFÉ".replace("É", "É") } }))).status).toBe(409);
    const renamed = await demoApi<FolderAnswer>(`${folders}/${created.folder!.id}`, { method: "PATCH", body: { name: "Ünïcode 表" } });
    expect(renamed.folder?.name).toBe("Ünïcode 表");
    expect((await refused(demoApi(`${folders}/fld-nope`, { method: "PATCH", body: { name: "x" } }))).status).toBe(404);
    const { items } = await demoApi<{ items: EvidenceActivityItem[] }>(`/engagements/${ID}/evidence-activity`);
    expect(items[0]).toMatchObject({ event_type: "evidence_folder_renamed", new_label: "Ünïcode 表" });
    expect(items.map((i) => i.event_type)).toContain("evidence_folder_created");
  });

  it("puts a Block 1 document in a folder and out again, refuses a bill, and deleting a non-empty folder moves its documents to the top", async () => {
    const t = await tree();
    const docs = t.blocks.summary.map((d) => d.document_id);
    expect(docs.length).toBeGreaterThanOrEqual(2);
    const [a, b] = docs;
    const { folder } = await demoApi<FolderAnswer>(folders, { method: "POST", body: { name: "Workbooks" } });
    const id = folder!.id;
    expect((await inFolder(id, a, id)).payload.folderId).toBe(id);
    await inFolder(id, b, id);
    let now = await tree();
    expect(now.blocks.summary.find((d) => d.document_id === a)?.folder_id).toBe(id);
    expect(now.blocks.summary_folders?.find((f) => f.folder_id === id)?.documents).toBe(2);
    expect((await inFolder(id, a, null)).payload.folderId).toBeUndefined();
    await inFolder(id, a, id);

    const bill = (await demoApi<EvidenceTree>(`/engagements/${ID}/evidence-tree`)).blocks.supporting.scopes.flatMap((s) => s.categories.flatMap((c) => c.level2s.flatMap((l) => l.lines.flatMap((n) => n.documents))))[0];
    expect((await refused(inFolder(id, bill.document_id, id))).status).toBe(422);
    expect((await refused(inFolder("fld-nope", a, "fld-nope"))).status).toBe(404);

    const deleted = await demoApi<FolderAnswer>(`${folders}/${id}`, { method: "DELETE" });
    expect(deleted.documents_moved).toBe(2);
    expect(Object.keys(deleted.documents ?? {}).sort()).toEqual([a, b].sort());
    now = await tree();
    expect(now.blocks.summary.find((d) => d.document_id === a)?.folder_id).toBeNull();
    expect(now.blocks.summary_folders?.some((f) => f.folder_id === id)).toBe(false);
    expect(demoDecisions().get(a)?.folderId).toBeUndefined();
    expect((await refused(demoApi(`${folders}/${id}`, { method: "DELETE" }))).status).toBe(404);
  });

  it("a document moved onto a line leaves its folder, and back again it is at the top of Block 1", async () => {
    const t = await tree();
    const doc = t.blocks.summary[0].document_id;
    const line = t.lines[0].key;
    const { folder } = await demoApi<FolderAnswer>(folders, { method: "POST", body: { name: "Round trip" } });
    await inFolder(folder!.id, doc, folder!.id);
    const move = (from: string, to: string) => demoApi(`/engagements/${ID}/documents/${doc}/placements`, { method: "POST", body: { from, to } });
    await move(BLOCK_1, line);
    expect((await tree()).blocks.summary.some((d) => d.document_id === doc)).toBe(false);
    expect((await refused(inFolder(folder!.id, doc, folder!.id))).status).toBe(422);
    await move(line, BLOCK_1);
    const back = (await tree()).blocks.summary.find((d) => d.document_id === doc);
    expect(back?.folder_id).toBeNull();
  });
});
