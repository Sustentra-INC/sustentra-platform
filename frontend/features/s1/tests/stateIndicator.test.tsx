import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { StateIndicator } from "../components/StateIndicator";
import { STATE_ROLE_BY_PAIR } from "../constants/stateIndicators";

describe("StateIndicator", () => {
  it("renders a visible unmapped marker for unknown dimension/value pairs", () => {
    const html = renderToStaticMarkup(
      <StateIndicator dimension="processing" value="unknown" label="Unknown" />
    );

    expect(html).toContain("unmapped: Unknown");
    expect(html).toContain("s1-state--unmapped");
  });

  it("keeps the full S1 state-role table explicit", () => {
    expect(STATE_ROLE_BY_PAIR).toEqual({
      processing: {
        not_ingested: "active",
        ingested: "active",
        typed: "active",
        extracted: "active",
        blocked: "blocking",
      },
      facilityResolution: {
        resolved: "resolved",
        unresolved: "open",
        multiple: "unverifiable",
        not_facility_scoped: "na",
      },
      periodResolution: {
        resolved: "resolved",
        unresolved: "open",
        spans_multiple: "unverifiable",
      },
      field: {
        populated: "active",
        missing_requestable: "open",
        missing_not_requestable: "unverifiable",
        system_key: "na",
        not_applicable: "na",
      },
      valueProperty: {
        estimated_read: "open",
        unit_missing: "open",
        unit_ambiguous: "open",
        format_mismatch: "open",
      },
      review: {
        unreviewed: "na",
        accepted: "resolved",
        corrected: "resolved",
        keyed_by_reviewer: "resolved",
      },
      readiness: {
        "non-blocking": "open",
        blocking: "blocking",
      },
      check: {
        not_system_verified: "unverifiable",
        not_applicable: "na",
        passed: "resolved",
        failed: "blocking",
        not_evaluable: "unverifiable",
      },
      disposition: {
        active: "na",
        withdrawn: "na",
      },
      request: {
        requested: "active",
        fulfilled: "resolved",
        cancelled: "na",
        waived_below_threshold: "unverifiable",
      },
    });
  });

  it("renders focusable tooltip markup when an explanation is present", () => {
    const html = renderToStaticMarkup(
      <StateIndicator dimension="processing" value="blocked" label="Blocked" explain="Readable on focus." />
    );

    expect(html).toContain("tabindex=\"0\"");
    expect(html).toContain("role=\"tooltip\"");
    expect(html).toContain("Readable on focus.");
  });
});
