/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

import { createDocumentBatch, getDocumentBatch } from "../api/documentBatches";
import { AiTypeNote } from "../components/AiTypeNote";
import { AiValueNote } from "../components/AiValueNote";
import { DemoDocument } from "../components/demo/DemoDocument";
import { ExtractionReview } from "../components/ExtractionReview";
import { demoApi } from "../demo-backend";
import { PARTIAL_REASON, registerDemoBatch } from "../demo-backend/batches";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";

beforeAll(() => {
  vi.stubEnv("NEXT_PUBLIC_S1_DATA_MODE", "fixture");
});
afterAll(() => {
  vi.unstubAllEnvs();
});

const ENG = "ENG-CASCADE-2025";
const files = ["kent_gas_nov.pdf", "kent_fleet_q4.pdf", "scan_0042.jpg", "tualatin_electric_nov.pdf", "notes.xlsx"].map((fileName, i) => ({
  documentId: `UP-${i}`,
  fileName,
}));

async function poll(batchId: string, times: number) {
  const views = [];
  for (let i = 0; i < times; i += 1) views.push(await getDocumentBatch(ENG, batchId));
  return views;
}

describe("the demo backend's document batches", () => {
  it("makes a batch with the contract's shape and 404s an unknown one", async () => {
    const created = await demoApi<Record<string, unknown>>(`/engagements/${ENG}/document-batches`, { method: "POST", body: { label: "Nov" } });
    expect(Object.keys(created).sort()).toEqual(["batch_id", "created_at", "engagement_id", "label"]);
    expect(created.label).toBe("Nov");
    await expect(demoApi(`/engagements/${ENG}/document-batches/nope`)).rejects.toMatchObject({ status: 404 });
  });

  it("reads the dropped files: queued, then reading with chunk progress, then done, one partial, one typed by Claude", async () => {
    const id = await createDocumentBatch(ENG);
    registerDemoBatch(id, files);
    const views = await poll(id, 8);

    const first = views[0];
    expect(first.items.map((i) => i.file_name)).toEqual(files.map((f) => f.fileName));
    expect(first.items.map((i) => i.document_id)).toEqual(files.map((f) => f.documentId));
    expect(first.items[0].status).toBe("reading");
    expect(first.items[0].chunks).toMatchObject({ total: 30, completed: 6 });
    expect(first.items[4].status).toBe("queued");
    expect(first.complete).toBe(false);
    expect(views[1].items[0].chunks?.completed).toBe(12);

    const last = views[views.length - 1];
    expect(last.complete).toBe(true);
    expect(last.totals).toMatchObject({ queued: 0, reading: 0, done: 4, partial: 1 });
    const partial = last.items.find((i) => i.status === "partial")!;
    expect(partial.halt_reason).toBe(PARTIAL_REASON);
    expect(partial.halt_reason).toContain("pages 21–30");
    expect(partial.chunks).toMatchObject({ total: 30, completed: 20, failed: 10, failed_pages: [[21, 30]] });
    // a file name no rule recognises is typed by Claude; the rest by their names
    expect(last.items.find((i) => i.file_name === "scan_0042.jpg")?.canonical_type_id).not.toBeNull();
    expect(last.items.find((i) => i.file_name === "tualatin_electric_nov.pdf")?.canonical_type_id).toBe("CT-S2-ELEC");
    // progress only moves forward
    const order = ["queued", "reading", "done", "partial"];
    for (const i of last.items.keys()) {
      let prev = 0;
      for (const v of views) {
        const at = order.indexOf(v.items[i].status);
        expect(at).toBeGreaterThanOrEqual(prev);
        prev = at;
      }
    }
  });
});

describe("Claude's readings on the demo documents", () => {
  const aiValues = manufacturerValues.filter((v) => v.ai);

  it("covers four documents with suggestions, a disagreement, a conflict and one unconfirmed type", () => {
    const suggested = aiValues.filter((v) => v.ai?.suggested && !v.ai.conflict);
    expect(new Set(aiValues.map((v) => v.filename)).size).toBe(4);
    expect(suggested.length).toBeGreaterThanOrEqual(3);
    expect(aiValues.every((v) => v.reviewState === "to_review")).toBe(true);
    expect(aiValues.filter((v) => v.ai?.disagrees)).toHaveLength(1);
    expect(aiValues.filter((v) => v.ai?.conflict)).toHaveLength(2);
    const typed = manufacturerEvidence.filter((d) => d.aiType);
    expect(typed).toHaveLength(1);
    expect(typed[0]).toMatchObject({ typeConfirmed: false, aiType: { used: true } });
  });

  it("quotes what the drawn document prints", () => {
    const strip = (t: string) => t.replace(/\s/g, "");
    const byDoc = new Map<string, typeof manufacturerValues>();
    for (const v of manufacturerValues) byDoc.set(v.documentId, [...(byDoc.get(v.documentId) ?? []), v]);
    for (const id of new Set(aiValues.map((v) => v.documentId))) {
      const values = byDoc.get(id)!;
      const { container, unmount } = render(
        <DemoDocument values={values} engagement={engagementConfig} selectedId={null} onPick={() => undefined} />
      );
      const text = strip(container.textContent ?? "");
      for (const v of values.filter((x) => x.ai)) {
        if (v.snippet) expect(text, `${v.filename}: ${v.snippet}`).toContain(strip(v.snippet));
        if (v.ai?.disagrees) expect(text).toContain(strip(v.ai.disagrees.quote));
      }
      unmount();
    }
  });

  it("shows the notes on the cards", () => {
    const heat = aiValues.find((v) => v.whatItIs === "Heat content")!;
    const one = render(<AiValueNote value={heat} />);
    expect(one.container).toHaveTextContent("Suggested by Claude");
    expect(one.container).toHaveTextContent(`“${heat.snippet}”`);
    one.unmount();
    const disagree = aiValues.find((v) => v.ai?.disagrees)!;
    const two = render(<AiValueNote value={disagree} />);
    expect(two.container).toHaveTextContent("Claude read a different value here");
    expect(two.container).toHaveTextContent("1,480 gal");
    expect(two.container).toHaveTextContent("page 2");
    two.unmount();
    render(<AiValueNote value={aiValues.find((v) => v.ai?.conflict)!} />);
    expect(screen.getByText("Claude read two different values here")).toBeInTheDocument();
  });

  it("shows the type note until the type is confirmed", () => {
    const item = manufacturerEvidence.find((d) => d.aiType)!;
    const { container, rerender } = render(<AiTypeNote item={item} />);
    expect(container).toHaveTextContent("Type suggested by Claude, please confirm");
    rerender(<AiTypeNote item={{ ...item, typeConfirmed: true }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows Claude's notes in the demo's Extraction review", () => {
    const doc = manufacturerEvidence.find((d) => d.filename === "kent_fleetcard_q2_2025.pdf")!;
    render(
      <ExtractionReview
        engagement={engagementConfig}
        values={manufacturerValues}
        onValuesChange={vi.fn()}
        initialDocumentId={doc.documentId}
        initialDocumentName={doc.filename}
        initialNodeKey={`F:${doc.facilityId}|T:${doc.detectedType}`}
        onSaveAsk={vi.fn()}
        onBack={vi.fn()}
      />
    );
    expect(screen.getAllByTestId("ai-value-note").length).toBeGreaterThan(0);
  });
});
