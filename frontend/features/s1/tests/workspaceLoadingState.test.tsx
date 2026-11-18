/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import type { BackendDocumentLike } from "../adapters/evidenceAdapter";
import { S1WorkpaperApp } from "../pages/S1WorkpaperApp";

/**
 * While the engagement's documents are being fetched, the screens that read them show the
 * loading surface. They never show "0 documents", "No documents yet" or "Nothing needs you"
 * for an engagement that only has not loaded yet.
 */

const USER = { email: "m.osei@example.com", firstName: "Mary", role: "org_member" as const, orgSlug: "acme" };

const ENGAGEMENT_ROW = {
  id: "ENG-1",
  org_id: "ORG-1",
  name: "FY2025 inventory",
  client_name: "Müller Käserei – Zürich",
  reporting_period_start: "2025-01-01",
  reporting_period_end: "2025-12-31",
  status: "active",
  settings: {},
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

const DOC: BackendDocumentLike = {
  document_id: "DOC-1",
  file_name: "Rechnung März 電気.pdf",
  mime_type: "application/pdf",
  uploaded_by: "m.osei@example.com",
  uploaded_at: "2026-10-28T10:00:00Z",
  processing_status: "not_started",
};

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** The documents answer, held back until the test releases it. */
let releaseDocuments: (response: Response) => void = () => {};
let documentsAnswer: Promise<Response>;

const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
  const path = String(input).replace(/^\/api\/v1/, "");
  if (path === "/auth/me") return json(200, { email: USER.email, role: USER.role });
  if (path === "/engagements") return json(200, { items: [ENGAGEMENT_ROW] });
  if (path === "/engagements/ENG-1/documents") return documentsAnswer;
  if (path === "/engagements/ENG-1/workpaper-items") return json(200, { items: [] });
  return json(404, { detail: "Not found." });
});

async function settle() {
  for (let i = 0; i < 8; i += 1) {
    await act(async () => {
      await Promise.resolve();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

const sidebarItem = (title: string) => document.querySelector(`.s1-side__item[title="${title}"]`) as HTMLElement;

async function open(view: "Dashboard" | "Evidence" | "Coverage & requests" | "Verification results" | "Output") {
  render(<S1WorkpaperApp user={USER} />);
  await settle();
  if (view !== "Dashboard") fireEvent.click(sidebarItem(view));
  await settle();
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockClear();
  documentsAnswer = new Promise<Response>((resolve) => {
    releaseDocuments = resolve;
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  window.localStorage.clear();
});

const EMPTY_WORDS = /No documents yet|0 documents|Nothing needs you|Drop the client/;

describe("workspace still loading", () => {
  it("Evidence shows loading, not the empty state, then the documents", async () => {
    await open("Evidence");
    expect(screen.getByLabelText("Loading evidence")).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_WORDS)).toBeNull();

    releaseDocuments(json(200, { items: [DOC] }));
    await settle();
    expect(screen.queryByLabelText("Loading evidence")).toBeNull();
    expect(screen.queryByText("No documents yet")).toBeNull();
    expect(screen.getByRole("heading", { name: "Evidence" })).toBeInTheDocument();
  });

  it("the dashboard shows loading, not 0 documents or an all-clear, until the documents are in", async () => {
    await open("Dashboard");
    expect(screen.getByLabelText("Loading evidence")).toBeInTheDocument();
    expect(screen.queryByText(EMPTY_WORDS)).toBeNull();
    expect(screen.queryByText("Nothing uploaded yet")).toBeNull();

    releaseDocuments(json(200, { items: [DOC] }));
    await settle();
    expect(screen.queryByText("Nothing uploaded yet")).toBeNull();
    expect(screen.getByText("1 documents in")).toBeInTheDocument();
  });

  it.each(["Coverage & requests", "Verification results", "Output"] as const)(
    "%s shows loading while the documents are fetched",
    async (view) => {
      await open(view);
      expect(screen.getByLabelText("Loading evidence")).toBeInTheDocument();
      expect(screen.queryByText(EMPTY_WORDS)).toBeNull();
      releaseDocuments(json(200, { items: [] }));
      await settle();
      expect(screen.queryByLabelText("Loading evidence")).toBeNull();
    }
  );
});

describe("workspace loaded", () => {
  it("an engagement with no documents shows the empty state once loaded", async () => {
    await open("Evidence");
    releaseDocuments(json(200, { items: [] }));
    await settle();
    expect(screen.queryByLabelText("Loading evidence")).toBeNull();
    expect(screen.getByText("No documents yet")).toBeInTheDocument();
  });
});

describe("workspace failed to load", () => {
  it("says what went wrong, offers a retry, and does not call the engagement empty", async () => {
    await open("Evidence");
    releaseDocuments(json(500, { detail: "The database is busy." }));
    await settle();
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't load the evidence");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText("No documents yet")).toBeNull();
    expect(screen.queryByLabelText("Loading evidence")).toBeNull();
  });
});
