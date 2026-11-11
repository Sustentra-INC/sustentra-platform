/* @vitest-environment jsdom */
import { describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render } from "@testing-library/react";

import { AddToRequestsModal, type AddToRequestsTarget } from "../components/AddToRequestsModal";
import { EvidenceRequests } from "../components/EvidenceRequests";
import { engagementConfig } from "../fixtures/engagementConfig";
import { seedAsks } from "../fixtures/requests/seedAsks";
import { coverageRules } from "../fixtures/verification/coverageRules";
import { useRequestsStore } from "../requests/requestsStore";

/**
 * Fixture/demo parity gate for the request screens. These snapshots were taken before the
 * screens learned to wait for the server, and they must come through unchanged: with the
 * fixture store's synchronous callbacks and no `serverRecordsActor`, the rendered DOM is
 * what it always was.
 */

function RequestsPage() {
  const store = useRequestsStore(seedAsks);
  return (
    <EvidenceRequests
      engagement={engagementConfig}
      asks={store.asks}
      coverage={{ rules: coverageRules }}
      valuesToReview={0}
      onReview={vi.fn()}
      onSaveAsk={store.saveAsk}
      onSend={(ids, lineNumbers) => store.sendAsks(ids, lineNumbers).requestNumber}
      onResolve={store.resolveAsk}
      onWithdraw={store.withdrawAsk}
      onEdit={store.editAsk}
      onRaiseFollowUp={vi.fn()}
      onOpenSource={vi.fn()}
    />
  );
}

const workspaceTarget: AddToRequestsTarget = {
  origin: "workspace_document",
  documentId: "DOC-PARTIAL",
  itemLabel: "kent_gas_sep_2025.pdf",
  facilityName: "Kent Cannery",
  period: "Sep 2025",
  arrival: "Uploaded",
  headerLine: "kent_gas_sep_2025.pdf · Kent Cannery · Sep 2025 · Uploaded",
  defaultType: "replace_document",
  prefill: "kent_gas_sep_2025.pdf · Kent Cannery · Sep 2025: ",
};

describe("request screens: fixture parity", () => {
  it("draws Coverage & requests as it always has, rows collapsed", () => {
    const { container } = render(<RequestsPage />);
    expect(container).toMatchSnapshot();
  });

  it("draws the Add to requests window for a workspace document as it always has", () => {
    const { container } = render(
      <AddToRequestsModal target={workspaceTarget} engagement={engagementConfig} onCancel={vi.fn()} onAdd={vi.fn()} />
    );
    expect(container).toMatchSnapshot();
  });
});
