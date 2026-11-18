/* @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import type { BackendDocumentLike } from "../adapters/evidenceAdapter";
import { S1WorkpaperApp } from "../pages/S1WorkpaperApp";

/**
 * While the engagement is loading, the context bar shows a placeholder. "Company not set" only
 * appears once the engagement has loaded without a client name.
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
let releaseEngagements: () => void = () => {};
let engagementsGate: Promise<void> = Promise.resolve();
let engagementRow: Record<string, unknown> = ENGAGEMENT_ROW;
let releaseDocuments: (response: Response) => void = () => {};
let documentsAnswer: Promise<Response>;

const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
  const path = String(input).replace(/^\/api\/v1/, "");
  if (path === "/auth/me") return json(200, { email: USER.email, role: USER.role });
  if (path === "/engagements") {
    await engagementsGate;
    return json(200, { items: [engagementRow] });
  }
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


beforeEach(() => {
  window.history.replaceState(null, "", "/");
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockClear();
  engagementRow = ENGAGEMENT_ROW;
  engagementsGate = new Promise<void>((resolve) => {
    releaseEngagements = resolve;
  });
  documentsAnswer = new Promise<Response>((resolve) => {
    releaseDocuments = resolve;
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const bar = () => document.querySelector(".s1-ctx") as HTMLElement;

describe("context bar while the engagement loads", () => {
  it("shows a placeholder, never 'Company not set', then the client name", async () => {
    render(<S1WorkpaperApp user={USER} />);
    await settle();
    expect(screen.queryByText("Company not set")).toBeNull();
    expect(bar()).toHaveTextContent("Loading…");
    fireEvent.click(screen.getByRole("button", { name: /Details/ }));
    expect(screen.queryByText("Company not set")).toBeNull();
    expect(document.querySelector(".s1-ctx__details")).not.toHaveTextContent(/^$/);

    releaseEngagements();
    releaseDocuments(json(200, { items: [DOC] }));
    await settle();
    expect(screen.queryByText("Company not set")).toBeNull();
    expect(bar()).not.toHaveTextContent("Loading…");
    expect(bar().querySelector(".s1-ctx__client")).toHaveTextContent("Müller Käserei – Zürich");
  });

  it("a loaded engagement without a client name says so", async () => {
    engagementRow = { ...ENGAGEMENT_ROW, client_name: "", name: "" };
    render(<S1WorkpaperApp user={USER} />);
    await settle();
    expect(screen.queryByText("Company not set")).toBeNull();
    releaseEngagements();
    releaseDocuments(json(200, { items: [] }));
    await settle();
    expect(bar().querySelector(".s1-ctx__client")).toHaveTextContent("Company not set");
  });

  it("shows a non-ASCII client and engagement name as they are", async () => {
    engagementRow = { ...ENGAGEMENT_ROW, client_name: "東京ガス株式会社 – Zürich", name: "FY2025 CO₂ °F" };
    render(<S1WorkpaperApp user={USER} />);
    releaseEngagements();
    releaseDocuments(json(200, { items: [] }));
    await settle();
    expect(bar().querySelector(".s1-ctx__client")).toHaveTextContent("東京ガス株式会社 – Zürich");
    expect(bar().querySelector(".s1-ctx__id")).toHaveTextContent("FY2025 CO₂ °F");
  });
});
