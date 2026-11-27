/* @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ActivityDrawer } from "../components/ActivityDrawer";
import { engagementActivity, type ActivityEntry } from "../utils/engagementActivity";
import type { Ask } from "../types/requests";
import { CoveragePanel } from "../components/CoveragePanel";
import { cardProvenance } from "../components/ExtractionReview";
import { ProvenanceLabel, provenanceText } from "../components/ProvenanceLabel";
import { coverageRules } from "../fixtures/verification/coverageRules";
import type { ReviewValue } from "../types/review";

afterEach(cleanup);

const AT = "2026-10-21T15:57:00Z";

describe("ProvenanceLabel", () => {
  it("reads Read by AI, Checked by system, and a person's action with their name", () => {
    expect(provenanceText({ source: "ai" })).toBe("Read by AI");
    expect(provenanceText({ source: "system" })).toBe("Checked by system");
    expect(provenanceText({ source: "human", action: "accepted", by: "M. Osei" })).toBe("Accepted by M. Osei");
    expect(provenanceText({ source: "human", action: "corrected", by: "M. Osei", detail: "was 42.31" })).toBe("Corrected by M. Osei · was 42.31");
  });

  it("never shows an id: a missing or id-shaped name reads a reviewer", () => {
    expect(provenanceText({ source: "human", action: "accepted" })).toBe("Accepted by a reviewer");
    expect(provenanceText({ source: "human", action: "accepted", by: "  " })).toBe("Accepted by a reviewer");
    expect(provenanceText({ source: "human", action: "examined", by: "3f2b8c1e-aaaa-bbbb-cccc-1234567890ab" })).toBe("Examined by a reviewer");
  });

  it("ignores a stray action on a machine source and a bad time", () => {
    expect(provenanceText({ source: "ai", action: "accepted", by: "M. Osei" })).toBe("Read by AI");
    expect(provenanceText({ source: "human", action: "accepted", by: "M. Osei", at: "not a date" })).toBe("Accepted by M. Osei");
  });

  it("draws an icon beside the words", () => {
    const { container } = render(<ProvenanceLabel source="system" />);
    expect(container.querySelector("svg")).not.toBeNull();
    expect(screen.getByText("Checked by system")).toBeInTheDocument();
  });

  it("handles huge unicode names without breaking", () => {
    const name = "Ægir Østergaard ".repeat(100);
    render(<ProvenanceLabel source="human" action="accepted" by={name} />);
    expect(screen.getByText(/^Accepted by Ægir/)).toBeInTheDocument();
  });
});

const value = (over: Partial<ReviewValue>): ReviewValue =>
  ({
    id: "v1",
    documentId: "D1",
    filename: "bill.pdf",
    documentType: "Electricity bill",
    period: "2025-11",
    whatItIs: "Electricity consumed",
    value: "42.31",
    unit: "kWh",
    reviewState: "to_review",
    page: 3,
    record: [{ kind: "machine", actor: "system", at: AT, action: "read" }],
    ...over,
  }) as ReviewValue;

const human = (action: string) => ({ kind: "human" as const, actor: "M. Osei", at: AT, action });

describe("Extraction review value cards", () => {
  it("a value the AI read reads Read by AI and never Accepted", () => {
    render(<div>{cardProvenance(value({ ai: { suggested: true } }), null)}</div>);
    expect(screen.getByText("Read by AI")).toBeInTheDocument();
    expect(screen.queryByText(/Accepted/)).toBeNull();
  });

  it("a value the rules read reads Read by system rules, never Read by AI", () => {
    render(<div>{cardProvenance(value({}), null)}</div>);
    expect(screen.getByText("Read by system rules")).toBeInTheDocument();
    expect(screen.queryByText("Read by AI")).toBeNull();
  });

  it("a value still to review never reads Accepted, whatever its record holds", () => {
    render(<div>{cardProvenance(value({ record: [human("accepted")] }), null)}</div>);
    expect(screen.queryByText(/Accepted/)).toBeNull();
  });

  it("a value not found on the document carries no reading label", () => {
    const { container } = render(<div>{cardProvenance(value({ missing: true }), null)}</div>);
    expect(container.querySelector("[data-provenance]")).toBeNull();
  });

  it("accepted, corrected and keyed values say who", () => {
    const { rerender } = render(<div>{cardProvenance(value({ reviewState: "accepted", record: [human("accepted")] }), null)}</div>);
    expect(screen.getByText(/^Accepted by M\. Osei/)).toBeInTheDocument();
    rerender(<div>{cardProvenance(value({ reviewState: "corrected", originalValue: "42.31", record: [human("corrected")] }), null)}</div>);
    expect(screen.getByText(/^Corrected by M\. Osei .*was 42\.31/)).toBeInTheDocument();
    rerender(<div>{cardProvenance(value({ reviewState: "corrected", originalValue: null, record: [human("added")] }), null)}</div>);
    expect(screen.getByText(/^Keyed by M\. Osei .*highlighted on page 3/)).toBeInTheDocument();
  });

  it("an accepted value with no human record reads Accepted by a reviewer, never Read by AI", () => {
    render(<div>{cardProvenance(value({ reviewState: "accepted", ai: { suggested: true } }), null)}</div>);
    expect(screen.getByText("Accepted by a reviewer")).toBeInTheDocument();
    expect(screen.queryByText("Read by AI")).toBeNull();
  });

  it("the fallback actor Reviewer reads a reviewer", () => {
    render(<div>{cardProvenance(value({ reviewState: "accepted", record: [{ kind: "human", actor: "Reviewer", at: AT, action: "accepted as read" }] }), null)}</div>);
    expect(screen.getByText(/^Accepted by a reviewer/)).toBeInTheDocument();
  });
});

describe("Coverage & requests", () => {
  it("check rows read Checked by system, and a requested row reads Requested by", () => {
    const rules = coverageRules.slice(0, 2);
    render(<CoveragePanel coverage={{ rules }} isRequested={() => false} onRequest={vi.fn()} />);
    expect(screen.getAllByText("Checked by system").length).toBeGreaterThan(0);
    cleanup();
    render(
      <CoveragePanel
        coverage={{ rules: [{ ...rules[0], status: "inputs_missing" }] }}
        isRequested={() => true}
        requestOf={() => ({ by: "M. Osei", at: AT })}
        onRequest={vi.fn()}
      />,
    );
    expect(screen.getByText(/^Requested by M\. Osei/)).toBeInTheDocument();
  });
});

const ask = (events: { kind: "raised" | "edited" | "sent" | "resolved" | "withdrawn" }[]) =>
  ({
    id: "A1",
    state: "requested",
    source: { origin: "data_point", itemLabel: "Gas bill", documentId: null },
    history: events.map((e) => ({ ...e, actorName: "M. Osei", actorLogin: "mosei", at: AT })),
  }) as unknown as Ask;

describe("Activity entries: every producer carries who and what, and nothing is inferred", () => {
  it("value decisions carry their code; an entry without one carries no label", () => {
    const log = engagementActivity({
      evidence: [],
      findings: [],
      asks: [],
      values: [value({ record: [{ ...human("some new verb"), code: "corrected" }, human("accepted")] })],
    });
    expect(log.map((e) => [e.source, e.action])).toEqual(expect.arrayContaining([["human", "corrected"], [undefined, undefined]]));
  });

  it("request events: sent reads Requested, a draft reads Added to requests, withdrawn and resolved say so, an edit has none", () => {
    const log = engagementActivity({
      evidence: [],
      findings: [],
      values: [],
      asks: [ask([{ kind: "raised" }, { kind: "edited" }, { kind: "sent" }, { kind: "resolved" }, { kind: "withdrawn" }])],
    });
    expect(log.map((e) => e.action)).toEqual(expect.arrayContaining(["queued", "requested", "resolved", "withdrawn"]));
    // The edit has no label, and the verb stays in its line.
    const edit = log.find((e) => e.what.startsWith("edited"))!;
    expect(edit.source).toBeUndefined();
    expect(log.filter((e) => e.source === "human")).toHaveLength(4);
  });

  it("uploads, findings and document edits carry no label", () => {
    const log = engagementActivity({
      evidence: [{ documentId: "D1", filename: "a.pdf", uploadedAt: AT, uploadedBy: { name: "A. Lee" } } as never],
      values: [],
      asks: [],
      findings: [{ registeredAt: AT, registeredBy: "A. Lee", dataPointLabel: "x" } as never],
    });
    expect(log.length).toBe(2);
    expect(log.every((e) => e.source === undefined)).toBe(true);
  });

  it("methodology entries pass their source and action through", () => {
    const log = engagementActivity({ evidence: [], values: [], asks: [], findings: [], methodology: [{ at: AT, who: "M. Osei", what: "edited x", source: "human", action: "adjusted" }] });
    expect([log[0].source, log[0].action]).toEqual(["human", "adjusted"]);
  });
});

describe("Activity drawer", () => {
  const row = (over: Partial<ActivityEntry>): ActivityEntry => ({ at: AT, who: "M. Osei", what: "did something", kind: "review", ...over });

  it("labels a person's decision with the same words, with the time once, in its column", () => {
    render(
      <ActivityDrawer
        onClose={vi.fn()}
        entries={[
          row({ what: "accepted: Electricity (bill.pdf)", source: "human", action: "accepted" }),
          row({ what: "sent a request: Gas bill", kind: "request", source: "human", action: "requested" }),
          row({ who: "A. Lee", what: "uploaded bill.pdf", kind: "upload" }),
        ]}
      />,
    );
    expect(screen.getByText(/^Accepted by M\. Osei$/)).toBeInTheDocument();
    expect(screen.getByText(/^Requested by M\. Osei$/)).toBeInTheDocument();
    expect(document.querySelectorAll("[data-provenance]")).toHaveLength(2);
    expect(screen.getByText("A. Lee").tagName).toBe("STRONG");
  });

  it("an unknown verb or an unknown source draws no label, and a suggestion is never Accepted", () => {
    render(
      <ActivityDrawer
        onClose={vi.fn()}
        entries={[
          row({ what: "Suggested by Sustentra's AI on methodology: X", who: "Sustentra's AI", kind: "methodology" }),
          row({ what: "frobnicated the thing", source: "human" }),
          row({ what: "reverted the thing", kind: "methodology" }),
        ]}
      />,
    );
    expect(document.querySelectorAll("[data-provenance]")).toHaveLength(0);
    expect(screen.queryByText(/Accepted/)).toBeNull();
  });

  it("a suggestion by the AI reads Read by AI and one by the rules reads Read by system rules", () => {
    render(
      <ActivityDrawer
        onClose={vi.fn()}
        entries={[row({ what: "Suggested by Sustentra's AI on methodology: X", source: "ai", kind: "methodology" }), row({ what: "Suggested by Sustentra's rules on methodology: Y", source: "system", kind: "methodology" })]}
      />,
    );
    expect(screen.getByText("Read by AI")).toBeInTheDocument();
    expect(screen.getByText("Read by system rules")).toBeInTheDocument();
  });
});
