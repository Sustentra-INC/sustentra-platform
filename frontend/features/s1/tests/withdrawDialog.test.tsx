/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "../components/ConfirmDialog";
import { EvidenceWorkspace } from "../components/EvidenceWorkspace";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import type { EvidenceItem } from "../types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function workspace(evidence: EvidenceItem[]) {
  const onEvidenceChange = vi.fn();
  render(
    <EvidenceWorkspace
      engagement={engagementConfig}
      evidence={evidence}
      asks={[]}
      onSaveAsk={vi.fn()}
      onEvidenceChange={onEvidenceChange}
      onOpenExtraction={vi.fn()}
    />
  );
  return onEvidenceChange;
}

function openWithdraw(filename: string) {
  // Types open on click: open the ones still shut so the row is on the page.
  for (const head of document.querySelectorAll<HTMLElement>('.s1-ws-gr__head[aria-expanded="false"]')) fireEvent.click(head);
  fireEvent.click(screen.getByRole("button", { name: `Actions for ${filename}` }));
  fireEvent.click(screen.getByRole("menuitem", { name: "Withdraw" }));
}

describe("Withdraw a document", () => {
  const target = manufacturerEvidence.find((i) => i.disposition !== "withdrawn")!;
  const small = [target]; // one row: opening every type of the demo set renders hundreds

  it("asks in the app's own window, never the browser's confirm()", () => {
    const confirm = vi.spyOn(window, "confirm");
    const onEvidenceChange = workspace(small);
    openWithdraw(target.filename);
    const dialog = screen.getByRole("dialog", { name: "Withdraw this document?" });
    expect(dialog).toHaveTextContent(target.filename);
    expect(dialog).toHaveTextContent("You can reinstate it");
    expect(confirm).not.toHaveBeenCalled();
    expect(onEvidenceChange).not.toHaveBeenCalled(); // nothing is withdrawn until the reviewer says so
    // the cursor starts on Cancel, so a stray Enter does not confirm
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  });

  it("withdraws only after Withdraw is clicked in the window", () => {
    const onEvidenceChange = workspace(small);
    openWithdraw(target.filename);
    fireEvent.click(screen.getByRole("button", { name: /^Withdraw$/ }));
    expect(onEvidenceChange).toHaveBeenCalledTimes(1);
    const updater = onEvidenceChange.mock.calls[0][0] as (cur: EvidenceItem[]) => EvidenceItem[];
    const next = updater(small);
    expect(next.find((i) => i.documentId === target.documentId)?.disposition).toBe("withdrawn");
    expect(next.filter((i) => i.disposition === "withdrawn")).toHaveLength(1);
    expect(screen.queryByRole("dialog", { name: "Withdraw this document?" })).toBeNull();
    expect(screen.getByText(`Withdrew ${target.filename}`)).toBeInTheDocument();
  });

  it("cancels with Cancel, with Escape and with a click outside, and changes nothing", () => {
    const onEvidenceChange = workspace(small);
    openWithdraw(target.filename);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog", { name: "Withdraw this document?" })).toBeNull();
    openWithdraw(target.filename);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: "Withdraw this document?" })).toBeNull();
    openWithdraw(target.filename);
    const scrim = document.querySelector(".s1-modal-scrim") as HTMLElement;
    fireEvent.pointerDown(scrim);
    expect(screen.queryByRole("dialog", { name: "Withdraw this document?" })).toBeNull();
    expect(onEvidenceChange).not.toHaveBeenCalled();
  });

  it("names a file with non-ASCII characters in the window", () => {
    const name = "Müller Käserei – Zürich 北京.pdf";
    workspace([{ ...target, filename: name }]);
    openWithdraw(name);
    expect(screen.getByRole("dialog", { name: "Withdraw this document?" })).toHaveTextContent(name);
  });
});

describe("ConfirmDialog", () => {
  it("shows the message and the named action, and calls back once per click", () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ConfirmDialog title="Remove it?" message="It goes away." confirmLabel="Remove" onConfirm={onConfirm} onCancel={onCancel} />);
    expect(screen.getByRole("dialog", { name: "Remove it?" })).toHaveAccessibleDescription("It goes away.");
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
  });
});
