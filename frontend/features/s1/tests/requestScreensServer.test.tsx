/* @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useState, type ComponentProps } from "react";

import { AddToRequestsModal, type AddToRequestsTarget } from "../components/AddToRequestsModal";
import { EvidenceRequests } from "../components/EvidenceRequests";
import { EvidenceWorkspace } from "../components/EvidenceWorkspace";
import { ExtractionReview } from "../components/ExtractionReview";
import { engagementConfig } from "../fixtures/engagementConfig";
import { manufacturerEvidence } from "../fixtures/evidence/manufacturerEvidence";
import { manufacturerValues } from "../fixtures/extraction/manufacturerValues";
import { seedAsks } from "../fixtures/requests/seedAsks";
import { coverageRules } from "../fixtures/verification/coverageRules";
import { andThen, problemText, settle } from "../requests/maybePromise";
import { whoActed } from "../requests/whoActed";
import type { Ask } from "../types/requests";
import type { ReviewValue } from "../types/review";

/**
 * The request screens wait for the server when a callback answers late, say what went wrong when
 * it fails, and (when the server records the signed-in user) stop asking who raised a request.
 * With plain callbacks nothing changes: see requestScreensFixtureParity.test.tsx.
 */

const NOT_SAVED = "That change wasn't saved";
const SCAN = "scan_0417.pdf"; // seedAsks[0]: requested, request 1
const KENT = "kent_gas_sep_2025.pdf"; // seedAsks[1]: not yet sent

afterEach(() => vi.useRealTimers());

function deferred<T = void>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function renderRequests(props: Partial<ComponentProps<typeof EvidenceRequests>> = {}, asks: Ask[] = seedAsks) {
  const handlers = {
    onSaveAsk: vi.fn(),
    onSend: vi.fn(() => 1),
    onResolve: vi.fn(),
    onWithdraw: vi.fn(),
    onEdit: vi.fn(),
    onRaiseFollowUp: vi.fn(),
  };
  const view = render(
    <EvidenceRequests
      engagement={engagementConfig}
      asks={asks}
      coverage={{ rules: coverageRules }}
      valuesToReview={0}
      onReview={vi.fn()}
      onOpenSource={vi.fn()}
      {...handlers}
      {...props}
    />
  );
  return { ...handlers, ...view };
}

const rowOf = (label: string) => screen.getByRole("button", { name: label }).closest("tr") as HTMLElement;
const openBox = () => document.querySelector(".s1-req-box") as HTMLElement | null;

/** A second request that is out, so two rows can have a box open one after the other. */
const SECOND = "second_scan.pdf";
const secondRequested: Ask = {
  ...seedAsks[0],
  id: "ASK-SEED-4",
  requestNumber: 2,
  source: { ...seedAsks[0].source, documentId: "DOC-SECOND", itemLabel: SECOND },
};
/** A second request that is not yet sent. */
const OCTOBER = "kent_gas_oct_2025.pdf";
const secondUnsent: Ask = {
  ...seedAsks[1],
  id: "ASK-SEED-3",
  source: { ...seedAsks[1].source, documentId: "DOC-OCT", itemLabel: OCTOBER },
};

function openResolve(label = SCAN) {
  fireEvent.click(within(rowOf(label)).getByRole("button", { name: "Resolve" }));
  return within(openBox()!).getByRole("button", { name: "Resolve" });
}

function openWithdraw(reason: string, label = SCAN) {
  fireEvent.click(within(rowOf(label)).getByRole("button", { name: `Actions for ${label}` }));
  fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "Withdraw" }));
  fireEvent.change(within(openBox()!).getByLabelText("Reason (required)"), { target: { value: reason } });
  return within(openBox()!).getByRole("button", { name: "Withdraw" });
}

function openSend(label = KENT) {
  fireEvent.click(screen.getByRole("checkbox", { name: `Select ${label}` }));
  fireEvent.click(screen.getByRole("button", { name: /^Send \(1\)/ }));
  return screen.getByRole("dialog", { name: "Send requests" });
}

describe("settle, andThen and problemText", () => {
  it("settle runs onDone at once for a plain value", () => {
    const done = vi.fn();
    const failed = vi.fn();
    settle(() => 7, done, failed);
    expect(done).toHaveBeenCalledWith(7);
    expect(failed).not.toHaveBeenCalled();
  });

  it("settle waits for a promise, and sends a rejection or a throw to onError", async () => {
    const done = vi.fn();
    const failed = vi.fn();
    const later = deferred<number>();
    settle(() => later.promise, done, failed);
    expect(done).not.toHaveBeenCalled();
    later.resolve(3);
    await later.promise;
    expect(done).toHaveBeenCalledWith(3);

    const boom = new Error("no");
    const rejected = Promise.reject(boom);
    settle(() => rejected, done, failed);
    await rejected.catch(() => undefined);
    expect(failed).toHaveBeenCalledWith(boom);

    const thrown = new Error("thrown");
    settle(
      () => {
        throw thrown;
      },
      done,
      failed
    );
    expect(failed).toHaveBeenLastCalledWith(thrown);
    expect(done).toHaveBeenCalledTimes(1);
  });

  it("andThen stays synchronous for a plain value and chains a promise", async () => {
    expect(andThen(2, (n) => n + 1)).toBe(3);
    await expect(andThen(Promise.resolve(2), (n) => n + 1)).resolves.toBe(3);
    await expect(andThen(Promise.reject(new Error("x")), (n: number) => n + 1)).rejects.toThrow("x");
  });

  it("problemText gives an error's own sentence, else a plain one", () => {
    expect(problemText(new Error("Request 3 is already withdrawn."))).toBe("Request 3 is already withdrawn.");
    expect(problemText(new Error(""))).toBe("That change wasn't saved. Try again.");
    expect(problemText("boom")).toBe("That change wasn't saved. Try again.");
    expect(problemText(undefined)).toBe("That change wasn't saved. Try again.");
  });
});

describe("fixture timing is unchanged", () => {
  it("resolves at once with plain callbacks: the toast shows with no await, and there is no alert", () => {
    const view = renderRequests();
    fireEvent.click(openResolve());

    expect(screen.getByText(`Resolved: ${SCAN}`)).toBeInTheDocument();
    expect(openBox()).toBeNull();
    expect(view.onResolve).toHaveBeenCalledTimes(1);
    expect(view.onResolve).toHaveBeenCalledWith("ASK-SEED-1", { link: null, note: null });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("withdraws, sends and edits at once with plain callbacks", () => {
    const view = renderRequests();
    fireEvent.click(openWithdraw("found on the next bill"));
    expect(screen.getByText("Withdrawn")).toBeInTheDocument();
    expect(openBox()).toBeNull();
    expect(view.onWithdraw).toHaveBeenCalledWith("ASK-SEED-1", "found on the next bill");

    const input = screen.getByLabelText("What is needed");
    fireEvent.change(input, { target: { value: "Please re-send the Kent bill." } });
    fireEvent.blur(input);
    expect(view.onEdit).toHaveBeenCalledWith("ASK-SEED-2", "Please re-send the Kent bill.");

    const panel = openSend();
    fireEvent.click(within(panel).getByRole("button", { name: "Mark as sent" }));
    expect(view.onSend).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Sent as request 1")).toBeInTheDocument();
    expect(screen.queryByRole("dialog", { name: "Send requests" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("the Add to requests window: who raised it", () => {
  const target: AddToRequestsTarget = {
    origin: "workspace_document",
    documentId: "DOC-PARTIAL",
    itemLabel: KENT,
    facilityName: "Kent Cannery",
    period: "Sep 2025",
    headerLine: "header",
    defaultType: "clarify",
    prefill: "Please confirm.",
  };

  it("asks who raised it without the prop, and uses the person picked", () => {
    const onAdd = vi.fn();
    render(<AddToRequestsModal target={target} engagement={engagementConfig} onCancel={vi.fn()} onAdd={onAdd} />);
    fireEvent.change(screen.getByLabelText("Raised by"), { target: { value: "riqbal" } });
    fireEvent.click(screen.getByRole("button", { name: "Add to requests" }));
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ raisedByName: "R. Iqbal", raisedByLogin: "riqbal" }));
  });

  it("does not ask with serverRecordsActor, and sends the signed-in person", () => {
    const onAdd = vi.fn();
    render(<AddToRequestsModal target={target} engagement={engagementConfig} onCancel={vi.fn()} onAdd={onAdd} serverRecordsActor />);
    expect(screen.queryByText("Raised by")).toBeNull();
    expect(screen.getByLabelText("Request type")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add to requests" }));
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ raisedByName: "M. Osei", raisedByLogin: "mosei" }));
  });

  it("uses the signed-in name when the engagement has one and no team", () => {
    const onAdd = vi.fn();
    const alone = { ...engagementConfig, engagementTeam: [], signedInLogin: "cng", signedInName: "Claire Ng" };
    render(<AddToRequestsModal target={target} engagement={alone} onCancel={vi.fn()} onAdd={onAdd} serverRecordsActor />);
    fireEvent.click(screen.getByRole("button", { name: "Add to requests" }));
    expect(onAdd).toHaveBeenCalledWith(expect.objectContaining({ raisedByName: "Claire Ng", raisedByLogin: "cng" }));
  });

  it("cannot be closed while the save is on its way, and can again once it has failed", async () => {
    const saving = deferred<unknown>();
    const onCancel = vi.fn();
    render(<AddToRequestsModal target={target} engagement={engagementConfig} onCancel={onCancel} onAdd={() => saving.promise} />);
    const scrim = screen.getByRole("dialog").parentElement!;
    fireEvent.click(screen.getByRole("button", { name: "Add to requests" }));

    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(scrim);
    expect(onCancel).not.toHaveBeenCalled();

    await act(async () => saving.reject(new Error("Nope.")));
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(scrim);
    expect(onCancel).toHaveBeenCalledTimes(4);
  });

  it("waits for the save: the button is off while it is pending, and the window stays after a failure", async () => {
    const saving = deferred<unknown>();
    const onAdd = vi.fn(() => saving.promise);
    render(<AddToRequestsModal target={target} engagement={engagementConfig} onCancel={vi.fn()} onAdd={onAdd} serverRecordsActor />);
    fireEvent.change(screen.getByLabelText("What is needed"), { target: { value: "Send the September bill." } });
    const add = screen.getByRole("button", { name: "Add to requests" });
    fireEvent.click(add);
    expect(add).toBeDisabled();
    fireEvent.submit(add.closest("form")!);
    expect(onAdd).toHaveBeenCalledTimes(1);

    await act(async () => saving.reject(new Error("This engagement is archived, so its requests can't change.")));
    expect(screen.getByRole("alert")).toHaveTextContent("This engagement is archived, so its requests can't change.");
    expect(screen.getByLabelText("What is needed")).toHaveValue("Send the September bill.");
    expect(add).toBeEnabled();

    fireEvent.change(screen.getByLabelText("What is needed"), { target: { value: "  " } });
    expect(add).toBeDisabled();
  });
});

describe("Coverage & requests waits for the server", () => {
  it("keeps the resolve box open and its button off until the server answers, then closes it", async () => {
    const saving = deferred();
    const onResolve = vi.fn(() => saving.promise);
    renderRequests({ onResolve });
    const confirm = openResolve();
    fireEvent.click(confirm);

    expect(onResolve).toHaveBeenCalledWith("ASK-SEED-1", { link: null, note: null });
    expect(openBox()).not.toBeNull();
    expect(confirm).toBeDisabled();
    expect(screen.queryByText(`Resolved: ${SCAN}`)).toBeNull();

    await act(async () => saving.resolve());
    expect(openBox()).toBeNull();
    expect(screen.getByText(`Resolved: ${SCAN}`)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says why a withdraw failed, keeps the box open, and lets the person try again", async () => {
    const saving = deferred();
    const onWithdraw = vi.fn(() => saving.promise);
    renderRequests({ onWithdraw });
    const confirm = openWithdraw("sent in error");
    fireEvent.click(confirm);
    expect(confirm).toBeDisabled();

    await act(async () => saving.reject(new Error("Request 3 is already withdrawn.")));

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(NOT_SAVED);
    expect(alert).toHaveTextContent("Request 3 is already withdrawn.");
    expect(openBox()).not.toBeNull();
    expect(confirm).toBeEnabled();
    expect(screen.queryByText("Withdrawn")).toBeNull();

    onWithdraw.mockResolvedValueOnce(undefined);
    fireEvent.click(confirm);
    // Starting the change again clears the message.
    expect(screen.queryByRole("alert")).toBeNull();
    await waitFor(() => expect(openBox()).toBeNull());
    expect(screen.getByText("Withdrawn")).toBeInTheDocument();
  });

  it("does not close the resolve box of another request when an earlier resolve answers late", async () => {
    const first = deferred();
    const onResolve = vi.fn(() => first.promise);
    renderRequests({ onResolve }, [seedAsks[0], secondRequested]);
    fireEvent.click(openResolve(SCAN));
    expect(onResolve).toHaveBeenCalledTimes(1);

    // The person moves on to the other request while the first is on its way.
    openResolve(SECOND);
    expect(openBox()).not.toBeNull();

    await act(async () => first.resolve());
    expect(openBox()).not.toBeNull();
    expect(screen.getByText(`Resolved: ${SCAN}`)).toBeInTheDocument();
    expect(onResolve).toHaveBeenCalledTimes(1);
  });

  it("does not close the withdraw box of another request when an earlier withdraw answers late", async () => {
    const first = deferred();
    const onWithdraw = vi.fn(() => first.promise);
    renderRequests({ onWithdraw }, [seedAsks[0], secondRequested]);
    fireEvent.click(openWithdraw("sent in error", SCAN));
    expect(onWithdraw).toHaveBeenCalledTimes(1);

    openWithdraw("also sent in error", SECOND);
    expect(openBox()).not.toBeNull();

    await act(async () => first.resolve());
    expect(openBox()).not.toBeNull();
    expect(within(openBox()!).getByLabelText("Reason (required)")).toHaveValue("also sent in error");
    expect(screen.getByText("Withdrawn")).toBeInTheDocument();
  });

  it("puts the text back and says why when an edit fails", async () => {
    const saving = deferred();
    const onEdit = vi.fn(() => saving.promise);
    renderRequests({ onEdit });
    const input = screen.getByLabelText("What is needed") as HTMLInputElement;
    const original = seedAsks[1].whatIsNeeded;
    expect(input.value).toBe(original);

    fireEvent.change(input, { target: { value: "Something else entirely." } });
    fireEvent.blur(input);
    expect(onEdit).toHaveBeenCalledWith("ASK-SEED-2", "Something else entirely.");
    expect(input.value).toBe("Something else entirely.");

    await act(async () => saving.reject(new Error("Request 3 was already sent, so its text can't change.")));
    expect(input.value).toBe(original);
    expect(screen.getByRole("alert")).toHaveTextContent("Request 3 was already sent, so its text can't change.");
  });

  it("does not save an edit that changed nothing", () => {
    const view = renderRequests();
    const input = screen.getByLabelText("What is needed");
    fireEvent.blur(input);
    expect(view.onEdit).not.toHaveBeenCalled();
  });

  it("keeps the send panel open with the reason when marking sent fails, and sends on a second try", async () => {
    const sending = deferred<number>();
    const onSend = vi.fn(() => sending.promise);
    renderRequests({ onSend });
    const panel = openSend();
    const markSent = within(panel).getByRole("button", { name: "Mark as sent" });
    fireEvent.click(markSent);
    expect(markSent).toBeDisabled();

    await act(async () => sending.reject(new Error("Request 3 was already sent.")));

    expect(screen.getByRole("dialog", { name: "Send requests" })).toBe(panel);
    expect(within(panel).getByRole("alert")).toHaveTextContent("Request 3 was already sent.");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    expect(markSent).toBeEnabled();
    expect(screen.queryByText(/^Sent as request/)).toBeNull();

    onSend.mockResolvedValueOnce(4);
    fireEvent.click(markSent);
    expect(within(panel).queryByRole("alert")).toBeNull();
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Send requests" })).toBeNull());
    expect(screen.getByText("Sent as request 4")).toBeInTheDocument();
  });

  it("does not close a send window opened since, or clear its selection, when an earlier send answers late", async () => {
    const sending = deferred<number>();
    const onSend = vi.fn(() => sending.promise);
    renderRequests({ onSend }, [seedAsks[0], seedAsks[1], secondUnsent]);
    const first = openSend(KENT);
    fireEvent.click(within(first).getByRole("button", { name: "Mark as sent" }));
    expect(onSend).toHaveBeenCalledTimes(1);

    // Close that window, choose the other request, and open the window again.
    fireEvent.click(first.parentElement!);
    fireEvent.click(screen.getByRole("checkbox", { name: `Select ${KENT}` }));
    fireEvent.click(screen.getByRole("checkbox", { name: `Select ${OCTOBER}` }));
    fireEvent.click(screen.getByRole("button", { name: /^Send \(1\)/ }));
    expect(screen.getByRole("dialog", { name: "Send requests" })).toBeInTheDocument();

    await act(async () => sending.resolve(7));
    expect(screen.getByRole("dialog", { name: "Send requests" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: `Select ${OCTOBER}` })).toBeChecked();
    // The first send did go through, and the toast says which request it became.
    expect(screen.getByText("Sent as request 7")).toBeInTheDocument();
  });

  it("does not clear a selection made after the send window was closed, when the send answers late", async () => {
    const sending = deferred<number>();
    renderRequests({ onSend: vi.fn(() => sending.promise) }, [seedAsks[0], seedAsks[1], secondUnsent]);
    const panel = openSend(KENT);
    fireEvent.click(within(panel).getByRole("button", { name: "Mark as sent" }));
    fireEvent.click(panel.parentElement!);
    expect(screen.queryByRole("dialog", { name: "Send requests" })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: `Select ${OCTOBER}` }));

    await act(async () => sending.resolve(7));
    expect(screen.getByRole("checkbox", { name: `Select ${OCTOBER}` })).toBeChecked();
  });

  it("takes what was sent out of the selection when the send answers after its window was closed", async () => {
    const sending = deferred<number>();
    renderRequests({ onSend: vi.fn(() => sending.promise) }, [seedAsks[0], seedAsks[1], secondUnsent]);
    const panel = openSend(KENT);
    fireEvent.click(within(panel).getByRole("button", { name: "Mark as sent" }));
    fireEvent.click(panel.parentElement!);
    expect(screen.queryByRole("dialog", { name: "Send requests" })).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: `Select ${OCTOBER}` }));
    expect(screen.getByRole("checkbox", { name: `Select ${KENT}` })).toBeChecked();

    await act(async () => sending.resolve(7));

    // Only what was sent is let go: the choice made for another send stays.
    expect(screen.getByRole("checkbox", { name: `Select ${KENT}` })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: `Select ${OCTOBER}` })).toBeChecked();
    expect(screen.getByText("Sent as request 7")).toBeInTheDocument();
  });

  it("does not carry a send failure into the next time the panel opens", async () => {
    renderRequests({ onSend: vi.fn(() => Promise.reject(new Error("Nope."))) });
    const panel = openSend();
    fireEvent.click(within(panel).getByRole("button", { name: "Mark as sent" }));
    await waitFor(() => expect(within(panel).getByRole("alert")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("dialog", { name: "Send requests" }).parentElement!);
    expect(screen.queryByRole("dialog", { name: "Send requests" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /^Send \(1\)/ }));
    expect(within(screen.getByRole("dialog", { name: "Send requests" })).queryByRole("alert")).toBeNull();
  });

  it("says why raising a follow-up failed", async () => {
    const resolved: Ask = {
      ...seedAsks[0],
      state: "resolved",
      resolution: { at: "2026-10-28T16:04:00.000Z", by: "Claire Ng" },
    };
    const onRaiseFollowUp = vi.fn(() => Promise.reject(new Error("This request is no longer in this engagement.")));
    renderRequests({ onRaiseFollowUp }, [resolved]);
    fireEvent.click(within(rowOf(SCAN)).getByRole("button", { name: `Actions for ${SCAN}` }));
    fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name: "Raise follow-up" }));
    expect(onRaiseFollowUp).toHaveBeenCalledWith(resolved);
    expect(await screen.findByRole("alert")).toHaveTextContent("This request is no longer in this engagement.");
  });

  describe("adding a request from a check that is missing its inputs", () => {
    const addFromCheck = () => {
      fireEvent.click(screen.getAllByRole("button", { name: /^Request$/ })[0]);
      return screen.getByRole("dialog", { name: "Add to requests" });
    };

    it("closes the window and says so only once the server has saved it", async () => {
      const saving = deferred();
      const onSaveAsk = vi.fn(() => saving.promise);
      renderRequests({ onSaveAsk }, []);
      const modal = addFromCheck();
      fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));
      expect(onSaveAsk).toHaveBeenCalledTimes(1);
      expect(screen.getByRole("dialog", { name: "Add to requests" })).toBe(modal);
      expect(screen.queryByText("Added to requests, not sent yet")).toBeNull();

      await act(async () => saving.resolve());
      expect(screen.queryByRole("dialog", { name: "Add to requests" })).toBeNull();
      expect(screen.getByText("Added to requests, not sent yet")).toBeInTheDocument();
    });

    it("stays open, and is not submitted twice, when it is closed while the save is on its way", async () => {
      const saving = deferred();
      const onSaveAsk = vi.fn(() => saving.promise);
      renderRequests({ onSaveAsk }, []);
      const modal = addFromCheck();
      fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));

      fireEvent.click(within(modal).getByRole("button", { name: "Cancel" }));
      fireEvent.keyDown(window, { key: "Escape" });
      fireEvent.click(modal.parentElement!);
      expect(screen.getByRole("dialog", { name: "Add to requests" })).toBe(modal);
      fireEvent.submit(within(modal).getByRole("button", { name: "Add to requests" }).closest("form")!);
      expect(onSaveAsk).toHaveBeenCalledTimes(1);

      await act(async () => saving.resolve());
      expect(screen.queryByRole("dialog", { name: "Add to requests" })).toBeNull();
      expect(screen.getByText("Added to requests, not sent yet")).toBeInTheDocument();
    });

    it("does not close, or toast over, a window opened since an earlier save was started", async () => {
      const saving = deferred();
      const onSaveAsk = vi.fn(() => saving.promise);
      renderRequests({ onSaveAsk }, []);
      const modal = addFromCheck();
      fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));

      // The window cannot be closed by hand now, so the next check is asked for from behind it.
      fireEvent.click(screen.getAllByRole("button", { name: /^Request$/ })[1]);
      fireEvent.change(within(modal).getByLabelText("What is needed"), { target: { value: "Typed for the second check." } });

      await act(async () => saving.resolve());
      expect(screen.getByRole("dialog", { name: "Add to requests" })).toBeInTheDocument();
      expect(within(modal).getByLabelText("What is needed")).toHaveValue("Typed for the second check.");
      expect(screen.queryByText("Added to requests, not sent yet")).toBeNull();
      expect(onSaveAsk).toHaveBeenCalledTimes(1);
    });

    it("stays open with the message and the typed text when the save fails", async () => {
      renderRequests({ onSaveAsk: vi.fn(() => Promise.reject(new Error("This request was already added. The list now shows it."))) }, []);
      const modal = addFromCheck();
      fireEvent.change(within(modal).getByLabelText("What is needed"), { target: { value: "Our own words." } });
      fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));

      expect(await within(modal).findByRole("alert")).toHaveTextContent("This request was already added. The list now shows it.");
      expect(screen.getByRole("dialog", { name: "Add to requests" })).toBe(modal);
      expect(within(modal).getByLabelText("What is needed")).toHaveValue("Our own words.");
      expect(within(modal).getByRole("button", { name: "Add to requests" })).toBeEnabled();
      expect(screen.queryByText("Added to requests, not sent yet")).toBeNull();
    });

    it("does not ask who raised it with serverRecordsActor", () => {
      renderRequests({ serverRecordsActor: true }, []);
      expect(within(addFromCheck()).queryByText("Raised by")).toBeNull();
    });
  });
});

describe("Coverage & requests: who acted", () => {
  const resolvedBy = (at: string): Ask => ({
    ...seedAsks[0],
    state: "resolved",
    resolution: { at, by: "Claire Ng" },
    history: [...seedAsks[0].history, { kind: "resolved", actorName: "Claire Ng", actorLogin: "cng", at }],
  });
  const note = () => rowOf(SCAN).querySelector(".s1-req-state__note") as HTMLElement | null;

  it("says who took the latest step and when, with serverRecordsActor", () => {
    renderRequests({ serverRecordsActor: true }, [resolvedBy("2026-10-28T16:04:00.000Z")]);
    expect(note()?.textContent).toMatch(/^Resolved by Claire Ng · \S/);
    expect(note()).toHaveClass("s1-muted");
  });

  it("says nothing of the kind without it", () => {
    renderRequests({}, [resolvedBy("2026-10-28T16:04:00.000Z")]);
    expect(note()).toBeNull();
    expect(screen.queryByText(/Resolved by/)).toBeNull();
  });

  it("puts the line before the link the request was answered by", () => {
    const ask = resolvedBy("2026-10-28T16:04:00.000Z");
    renderRequests({ serverRecordsActor: true }, [{ ...ask, resolution: { at: ask.resolution!.at, by: "Claire Ng", link: "the re-sent file" } }]);
    const notes = Array.from(rowOf(SCAN).querySelectorAll(".s1-req-state__note")).map((n) => n.textContent ?? "");
    expect(notes).toHaveLength(2);
    expect(notes[0]).toMatch(/^Resolved by Claire Ng/);
    expect(notes[1]).toBe("answered by the re-sent file");
  });

  it("shows the year only when it is not this year", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 28, 12, 0));

    const thisYear = renderRequests({ serverRecordsActor: true }, [resolvedBy(new Date(2026, 9, 28, 10, 4).toISOString())]);
    expect(note()?.textContent).toMatch(/^Resolved by Claire Ng · /);
    expect(note()?.textContent).not.toContain("2026");
    thisYear.unmount();

    renderRequests({ serverRecordsActor: true }, [resolvedBy(new Date(2025, 11, 30, 10, 4).toISOString())]);
    expect(note()?.textContent).toMatch(/^Resolved by Claire Ng · .*2025/);
  });

  it("says who raised a request that is not yet sent, and who sent one that is out", () => {
    renderRequests({ serverRecordsActor: true });
    expect(rowOf(KENT).querySelector(".s1-req-state__note")?.textContent).toMatch(/^Raised by M\. Osei · /);
    expect(rowOf(SCAN).querySelector(".s1-req-state__note")?.textContent).toMatch(/^Sent by M\. Osei · /);
  });
});

describe("whoActed", () => {
  const base = seedAsks[1];

  it("names who raised a request that is not yet sent", () => {
    expect(whoActed(base)).toEqual({ label: "Raised by M. Osei", at: "2025-09-15T09:40:00Z" });
  });

  it("names who sent a request that is out, from its sent event", () => {
    expect(whoActed(seedAsks[0])).toEqual({ label: "Sent by M. Osei", at: "2025-09-14T17:02:00Z" });
  });

  it("takes the last event of the step when there are several", () => {
    const ask: Ask = {
      ...base,
      state: "withdrawn",
      history: [
        ...base.history,
        { kind: "withdrawn", actorName: "A. First", actorLogin: "a", at: "2026-01-01T00:00:00Z" },
        { kind: "edited", actorName: "B. Other", actorLogin: "b", at: "2026-01-02T00:00:00Z" },
        { kind: "withdrawn", actorName: "C. Last", actorLogin: "c", at: "2026-01-03T00:00:00Z" },
      ],
    };
    expect(whoActed(ask)).toEqual({ label: "Withdrawn by C. Last", at: "2026-01-03T00:00:00Z" });
  });

  it("falls back to the resolution for a resolved request with no resolved event", () => {
    const ask: Ask = {
      ...seedAsks[0],
      state: "resolved",
      resolution: { at: "2025-10-01T08:00:00Z", by: "M. Osei" },
    };
    expect(whoActed(ask)).toEqual({ label: "Resolved by M. Osei", at: "2025-10-01T08:00:00Z" });
  });

  it("falls back to who raised it for a request with no raised event", () => {
    expect(whoActed({ ...base, history: [] })).toEqual({ label: "Raised by M. Osei", at: "2025-09-15T09:40:00Z" });
  });

  it("is null when the record names no one", () => {
    expect(whoActed({ ...seedAsks[0], history: [] })).toBeNull();
    expect(whoActed({ ...seedAsks[0], state: "withdrawn", history: [] })).toBeNull();
    expect(whoActed({ ...seedAsks[0], state: "resolved", history: [], resolution: null })).toBeNull();
    expect(whoActed({ ...base, raisedByName: "", history: [] })).toBeNull();
  });

  it("has no time when the record has none", () => {
    const ask: Ask = { ...seedAsks[0], state: "resolved", history: [], resolution: { at: "", by: "M. Osei" } };
    expect(whoActed(ask)).toEqual({ label: "Resolved by M. Osei", at: null });
  });
});

describe("Evidence waits for the server", () => {
  const bill = manufacturerEvidence.find((e) => e.detectedType === "Electricity bill" && e.disposition === "active")!;
  const answered: Ask = {
    ...seedAsks[0],
    id: "ASK-EVIDENCE",
    requestNumber: 4,
    source: { ...seedAsks[0].source, documentId: bill.documentId, itemLabel: bill.filename },
  };

  function renderEvidence(props: Partial<ComponentProps<typeof EvidenceWorkspace>> = {}, asks: Ask[] = []) {
    render(
      <EvidenceWorkspace
        engagement={engagementConfig}
        evidence={manufacturerEvidence}
        asks={asks}
        onSaveAsk={vi.fn()}
        onEvidenceChange={vi.fn()}
        onOpenExtraction={vi.fn()}
        {...props}
      />
    );
    fireEvent.click(screen.getAllByRole("button", { expanded: false }).find((b) => b.textContent?.startsWith("Electricity bill"))!);
  }

  const otherBill = manufacturerEvidence.find((e) => e.detectedType === "Electricity bill" && e.disposition === "active" && e !== bill)!;

  const menuAction = (name: string, filename = bill.filename) => {
    fireEvent.click(screen.getByRole("button", { name: `Actions for ${filename}` }));
    fireEvent.click(within(screen.getByRole("menu")).getByRole("menuitem", { name }));
  };

  it("says why a request could not be resolved, and does not toast that it was", async () => {
    const onAuditIntent = vi.fn();
    const onResolveAsk = vi.fn(() => Promise.reject(new Error("Request 4 is already resolved.")));
    renderEvidence({ onResolveAsk, onAuditIntent }, [answered]);
    menuAction("Answers request");

    expect(onResolveAsk).toHaveBeenCalledWith("ASK-EVIDENCE");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(NOT_SAVED);
    expect(alert).toHaveTextContent("Request 4 is already resolved.");
    expect(screen.queryByText(/^Resolved request/)).toBeNull();
    expect(onAuditIntent).not.toHaveBeenCalled();
  });

  it("toasts and records the resolve once the server has answered", async () => {
    const saving = deferred();
    const onAuditIntent = vi.fn();
    renderEvidence({ onResolveAsk: vi.fn(() => saving.promise), onAuditIntent }, [answered]);
    menuAction("Answers request");
    expect(screen.queryByText("Resolved request 4")).toBeNull();
    expect(onAuditIntent).not.toHaveBeenCalled();

    await act(async () => saving.resolve());
    expect(screen.getByText("Resolved request 4")).toBeInTheDocument();
    expect(onAuditIntent).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("toasts at once when the callback answers at once", () => {
    const onResolveAsk = vi.fn();
    renderEvidence({ onResolveAsk }, [answered]);
    menuAction("Answers request");
    expect(screen.getByText("Resolved request 4")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("clears an earlier failure when the next try starts", async () => {
    const onResolveAsk = vi.fn().mockRejectedValueOnce(new Error("Try later.")).mockResolvedValueOnce(undefined);
    renderEvidence({ onResolveAsk }, [answered]);
    menuAction("Answers request");
    expect(await screen.findByRole("alert")).toHaveTextContent("Try later.");
    menuAction("Answers request");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(await screen.findByText("Resolved request 4")).toBeInTheDocument();
  });

  it("keeps the Add to requests window open with the message when the save fails", async () => {
    renderEvidence({ onSaveAsk: vi.fn(() => Promise.reject(new Error("Your role can view requests but not change them."))) });
    menuAction("Add to requests");
    const modal = screen.getByRole("dialog", { name: "Add to requests" });
    fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));

    expect(await within(modal).findByRole("alert")).toHaveTextContent("Your role can view requests but not change them.");
    expect(screen.getByRole("dialog", { name: "Add to requests" })).toBe(modal);
    expect(screen.queryByText("Added to requests · not yet sent")).toBeNull();
  });

  it("cannot close the Add to requests window while the save is on its way", async () => {
    const saving = deferred();
    const onSaveAsk = vi.fn(() => saving.promise);
    renderEvidence({ onSaveAsk });
    menuAction("Add to requests");
    const modal = screen.getByRole("dialog", { name: "Add to requests" });
    fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));

    fireEvent.click(within(modal).getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(modal.parentElement!);
    expect(screen.getByRole("dialog", { name: "Add to requests" })).toBe(modal);
    await act(async () => saving.resolve());
    expect(screen.queryByRole("dialog", { name: "Add to requests" })).toBeNull();
  });

  it("does not close, or toast over, a window opened since an earlier save was started", async () => {
    const saving = deferred();
    renderEvidence({ onSaveAsk: vi.fn(() => saving.promise) });
    menuAction("Add to requests");
    const modal = screen.getByRole("dialog", { name: "Add to requests" });
    fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));

    // The window cannot be closed by hand now, so the next file's is asked for from behind it.
    menuAction("Add to requests", otherBill.filename);
    fireEvent.change(within(modal).getByLabelText("What is needed"), { target: { value: "Typed for the second file." } });

    await act(async () => saving.resolve());
    expect(screen.getByRole("dialog", { name: "Add to requests" })).toBeInTheDocument();
    expect(within(modal).getByLabelText("What is needed")).toHaveValue("Typed for the second file.");
    expect(screen.queryByText("Added to requests · not yet sent")).toBeNull();
  });

  it("closes the Add to requests window and toasts once the server has saved it, without asking who raised it", async () => {
    const saving = deferred();
    const onSaveAsk = vi.fn(() => saving.promise);
    renderEvidence({ onSaveAsk, serverRecordsActor: true });
    menuAction("Add to requests");
    const modal = screen.getByRole("dialog", { name: "Add to requests" });
    expect(within(modal).queryByText("Raised by")).toBeNull();
    fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));
    expect(screen.getByRole("dialog", { name: "Add to requests" })).toBe(modal);

    await act(async () => saving.resolve());
    expect(screen.queryByRole("dialog", { name: "Add to requests" })).toBeNull();
    expect(screen.getByText("Added to requests · not yet sent")).toBeInTheDocument();
  });
});

describe("Extraction review waits for the server", () => {
  const DOC = "DOC-tualatin-elec-jan";
  const raised = (over: Partial<Ask> = {}): Ask => ({
    ...seedAsks[1],
    id: "ASK-SERVER-1",
    source: { origin: "review_value", documentId: DOC, fieldKey: null, itemLabel: "Electricity bill", facilityName: null, period: null },
    ...over,
  });

  function renderReview(onSaveAsk: ComponentProps<typeof ExtractionReview>["onSaveAsk"], serverRecordsActor = false, documentId = DOC) {
    const live: { values: ReviewValue[] } = { values: manufacturerValues };
    function Harness() {
      const [values, setValues] = useState(manufacturerValues);
      live.values = values;
      return (
        <ExtractionReview
          engagement={engagementConfig}
          values={values}
          onValuesChange={setValues}
          initialDocumentId={documentId}
          onSaveAsk={onSaveAsk}
          serverRecordsActor={serverRecordsActor}
          onBack={vi.fn()}
          reviewerName="Thanishque"
        />
      );
    }
    const { container } = render(<Harness />);
    const card = () => container.querySelector<HTMLElement>(".s1-xr-card.is-sel")!;
    return {
      live,
      chip: () => card().querySelector(".s1-xr-badge")?.textContent,
      lines: () => Array.from(card().querySelectorAll(".s1-xr-rec__act")).map((n) => n.textContent),
      states: () => live.values.filter((v) => v.documentId === documentId).map((v) => v.reviewState),
      stateOf: (valueId: string) => live.values.find((v) => v.id === valueId)!.reviewState,
      cards: () => Array.from(container.querySelectorAll<HTMLElement>(".s1-xr-card")),
      selected: card,
      openWindow: () => {
        fireEvent.click(within(card()).getByRole("button", { name: "Request" }));
        return screen.getByRole("dialog", { name: "Add to requests" });
      },
    };
  }

  it("leaves the card alone, and the window open with the reason, when the save fails", async () => {
    const view = renderReview(() => Promise.reject(new Error("This engagement is archived, so its requests can't change.")));
    const before = view.states();
    expect(before.every((s) => s === "to_review")).toBe(true);
    const chipBefore = view.chip();

    const modal = view.openWindow();
    fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));

    expect(await within(modal).findByRole("alert")).toHaveTextContent("This engagement is archived, so its requests can't change.");
    expect(screen.getByRole("dialog", { name: "Add to requests" })).toBe(modal);
    expect(view.chip()).toBe(chipBefore);
    expect(view.states()).toEqual(before);
    expect(screen.queryByText("Added to requests · not yet sent")).toBeNull();
  });

  it("turns the values requested only after the save has gone through", async () => {
    const saving = deferred<Ask>();
    const view = renderReview(() => saving.promise);
    const modal = view.openWindow();
    fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));
    expect(view.states().every((s) => s === "to_review")).toBe(true);
    expect(screen.getByRole("dialog", { name: "Add to requests" })).toBe(modal);

    await act(async () => saving.resolve(raised()));
    expect(view.states().every((s) => s === "requested")).toBe(true);
    expect(screen.queryByRole("dialog", { name: "Add to requests" })).toBeNull();
    expect(screen.getByText("Added to requests · not yet sent")).toBeInTheDocument();
  });

  it("cannot close the window while the save is on its way", async () => {
    const saving = deferred<Ask>();
    const view = renderReview(() => saving.promise);
    const modal = view.openWindow();
    fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));

    fireEvent.click(within(modal).getByRole("button", { name: "Cancel" }));
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.click(modal.parentElement!);
    expect(screen.getByRole("dialog", { name: "Add to requests" })).toBe(modal);

    await act(async () => saving.resolve(raised()));
    expect(screen.queryByRole("dialog", { name: "Add to requests" })).toBeNull();
  });

  it("marks the first card requested but leaves a window opened since alone, when its save answers late", async () => {
    const GAS = "DOC-tualatin-gas-jan";
    const saving = deferred<Ask>();
    const view = renderReview(() => saving.promise, false, GAS);
    const firstId = view.selected().dataset.valueId!;
    const modal = view.openWindow();
    fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));

    // The window cannot be closed by hand now, so another card's is asked for from behind it.
    const other = view.cards().find((card) => card.dataset.valueId !== firstId)!;
    const otherId = other.dataset.valueId!;
    fireEvent.click(other);
    fireEvent.click(within(view.selected()).getByRole("button", { name: "Request" }));
    fireEvent.change(within(modal).getByLabelText("What is needed"), { target: { value: "Typed for the other card." } });

    await act(async () => saving.resolve(raised({ source: { ...raised().source, documentId: GAS, fieldKey: firstId } })));
    expect(view.stateOf(firstId)).toBe("requested");
    expect(view.stateOf(otherId)).toBe("to_review");
    expect(screen.getByRole("dialog", { name: "Add to requests" })).toBeInTheDocument();
    expect(within(modal).getByLabelText("What is needed")).toHaveValue("Typed for the other card.");
    expect(screen.queryByText("Added to requests · not yet sent")).toBeNull();
  });

  it("names the person and the time the server recorded, with serverRecordsActor", async () => {
    const ask = raised({ raisedByName: "Claire Ng", raisedAt: "2026-10-28T16:04:00.000Z" });
    const view = renderReview(() => Promise.resolve(ask), true);
    const modal = view.openWindow();
    expect(within(modal).queryByText("Raised by")).toBeNull();
    fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));

    await waitFor(() => expect(view.lines()).toContain("Claire Ng · added to requests"));
    expect(view.live.values.find((v) => v.documentId === DOC)!.record.at(-1)).toMatchObject({
      actor: "Claire Ng",
      at: "2026-10-28T16:04:00.000Z",
      action: "added to requests",
      askId: "ASK-SERVER-1",
    });
  });

  it("names the reviewer, as before, without serverRecordsActor", () => {
    const view = renderReview(() => raised({ raisedByName: "Claire Ng" }));
    const modal = view.openWindow();
    expect(within(modal).getByLabelText("Raised by")).toBeInTheDocument();
    fireEvent.click(within(modal).getByRole("button", { name: "Add to requests" }));
    expect(view.lines()).toContain("Thanishque · added to requests");
  });
});
