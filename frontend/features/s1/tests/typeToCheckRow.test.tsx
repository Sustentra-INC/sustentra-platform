/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { mapBackendDocumentToEvidenceItem } from "../adapters/evidenceAdapter";
import { EvidenceWorkspace } from "../components/EvidenceWorkspace";
import { AssignTaskProvider } from "../../tasks/AssignTaskContext";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EvidenceItem } from "../types";
import { applyDocumentView, decisionFromEdit } from "../utils/documentView";

afterEach(cleanup);

const document = {
  document_id: "DOC-1",
  file_name: "march-power-bill.pdf",
  uploaded_by: "u",
  uploaded_at: "2026-11-11T00:00:00Z",
  processing_status: "completed",
  evidence_id: "EV-1",
};
const read = () =>
  mapBackendDocumentToEvidenceItem(document, {
    canonical_type_id: "CT-S2-ELEC",
    canonical_type_source: "classifier",
    ai_routing: { canonical_type_id: "CT-S1-REFRSVC", quote: "Refrigerant charge log", page_number: 1, used: false, disagrees: true },
  });

function Harness({ onChange }: { onChange?: (items: EvidenceItem[]) => void }) {
  const [items, setItems] = useState<EvidenceItem[]>([read()]);
  return (
    <AssignTaskProvider orgId={null} engagementId={null}>
      <EvidenceWorkspace
        engagement={engagementConfig}
        evidence={items}
        asks={[]}
        onSaveAsk={vi.fn()}
        onEvidenceChange={(update) =>
          setItems((cur) => {
            const next = update(cur);
            onChange?.(next);
            return next;
          })
        }
        onOpenExtraction={vi.fn()}
        writesEnabled
        typeOptions={["Purchased electricity record", "Refrigerant service record"]}
      />
    </AssignTaskProvider>
  );
}

function open(container: HTMLElement) {
  for (const head of container.querySelectorAll(".s1-ws-gr__head")) fireEvent.click(head);
}

describe("a type to check on the Evidence row", () => {
  it("shows the words once, and confirming the type removes the mark and the count", () => {
    const { container } = render(<Harness />);
    open(container);
    expect(screen.getAllByText("Type to check")).toHaveLength(1);
    expect(screen.getByText(/The rules chose Purchased electricity record, but Sustentra's AI read the first pages as Refrigerant service record/)).toBeInTheDocument();
    expect(screen.getByText(/Refrigerant charge log/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm this type" })).toBeInTheDocument();
    expect(screen.getByLabelText("Set document type")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm this type" }));
    expect(screen.queryByText("Type to check")).toBeNull();
    expect(screen.queryByTestId("ai-type-note")).toBeNull();
    expect(screen.queryByRole("button", { name: "Confirm this type" })).toBeNull();
    expect(screen.queryByLabelText("Set document type")).toBeNull(); // the type is plain text again
  });

  it("changing the type also clears it", () => {
    const { container } = render(<Harness />);
    open(container);
    fireEvent.change(screen.getByLabelText("Set document type"), { target: { value: "Refrigerant service record" } });
    expect(screen.queryByTestId("ai-type-note")).toBeNull();
  });

  it("stays away when the document is read again, because the confirmation is a saved decision", () => {
    const before = read();
    const after = { ...before, typeConfirmed: true, typeReviewBand: null, typeReviewReason: null } as EvidenceItem;
    const decision = decisionFromEdit(before, after);
    expect(decision).toMatchObject({ documentId: "DOC-1", typeConfirmed: true });
    const [again] = applyDocumentView([read()], new Map(), { "DOC-1": decision! }, []);
    expect(again.typeConfirmed).toBe(true);
    expect(again.typeReviewBand).toBeNull();
    // and without a decision the fresh read does carry the mark
    expect(applyDocumentView([read()], new Map(), {}, [])[0].typeReviewBand).toBe("needs_review");
  });
});
