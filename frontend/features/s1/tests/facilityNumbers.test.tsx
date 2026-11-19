/* @vitest-environment jsdom */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { SetupScreen } from "../components/SetupScreen";
import { engagementConfig } from "../fixtures/engagementConfig";
import type { EngagementConfig, FacilityOption } from "../types/engagement";
import {
  addNumbers,
  checkNumber,
  matchByIdentifier,
  normaliseNumber,
  sameNumber,
  sharedNumberNote,
  sharedNumbers,
  splitPasted,
} from "../utils/facilityNumbers";

const KC: FacilityOption = { facilityId: "f-kc", name: "Müller Käserei – Zürich", address: "100 Main Street" };
const STL: FacilityOption = { facilityId: "f-stl", name: "工場 Plant", address: "200 Oak Avenue" };

describe("facility numbers: parsing and normalising", () => {
  it("splits a pasted list on newlines, commas and semicolons", () => {
    expect(splitPasted("4417-2290-31, 55 0012;  Zürich-№ 7\n\r\n 99.12.34 ;;, \n")).toEqual([
      "4417-2290-31", "55 0012", "Zürich-№ 7", "99.12.34",
    ]);
  });

  it("keeps a quoted value whole and drops its quotes", () => {
    expect(splitPasted('"4417, 22";"55;0012", 99-1234\n"Müller, Zürich 7"')).toEqual([
      "4417, 22", "55;0012", "99-1234", "Müller, Zürich 7",
    ]);
  });

  it("treats case, spaces, dashes and dots as the same, and nothing else", () => {
    expect(normaliseNumber("4417 2290 31")).toBe(normaliseNumber("4417-2290-31"));
    expect(normaliseNumber("AB 12–3")).toBe(normaliseNumber("ab.12-3"));
    expect(normaliseNumber("4417/2290")).not.toBe(normaliseNumber("44172290"));
    expect(normaliseNumber("ẞ12")).toBe("ss12"); // case folding, not just lower-casing
    expect(normaliseNumber("\ufeff4417\u200b-2290")).toBe("44172290"); // a BOM and a zero-width space are dropped
  });

  it("is the same number only with the same groups, or no separators on one side", () => {
    expect(sameNumber("4417 2290 31", "4417-2290-31")).toBe(true);
    expect(sameNumber("442290", "44-2290")).toBe(true);
    expect(sameNumber("12-345", "1234-5")).toBe(false);
    expect(sameNumber("4417-2290", "4417-2290-31")).toBe(false);
  });

  it("refuses an empty, digit-free or too long value with a sentence", () => {
    expect(checkNumber("  ")).toMatch(/empty/);
    expect(checkNumber("Zürich")).toMatch(/at least one digit/);
    expect(checkNumber("1".repeat(65))).toMatch(/64/);
    expect(checkNumber("工場 12")).toBeNull();
  });

  it("adds the good parts of a paste, skips duplicates and reports the first refusal", () => {
    const out = addNumbers(["4417-2290-31"], "4417 2290 31; Zürich; 55-0012");
    expect(out.values).toEqual(["4417-2290-31", "55-0012"]);
    expect(out.problem).toMatch(/^4417 2290 31: That number is already listed/);
    const full = addNumbers(Array.from({ length: 50 }, (_, i) => `${i}`), "99");
    expect(full.values).toHaveLength(50);
    expect(full.problem).toMatch(/at most 50/);
  });

  it("returns only the refused parts of a paste, so the input keeps just those", () => {
    const out = addNumbers([], "4417-2290-31; Zürich; 55-0012; ");
    expect(out.values).toEqual(["4417-2290-31", "55-0012"]);
    expect(out.rejected).toEqual(["Zürich"]);
  });
});

describe("facility numbers: matching", () => {
  const facilities = [{ ...KC, accountNumbers: ["4417-2290-31"], meterNumbers: ["Zähler E-55604"] }, STL];

  it("places a whole number, ignoring case, spaces, dashes and dots", () => {
    expect(matchByIdentifier("4417 2290 31", null, facilities).facility?.facilityId).toBe("f-kc");
    expect(matchByIdentifier(null, "zähler e.55604", facilities).facility?.facilityId).toBe("f-kc");
  });

  it("never matches a partial number", () => {
    for (const partial of ["4417-2290", "2290-31", "4417-2290-31-1"]) {
      expect(matchByIdentifier(partial, partial, facilities)).toEqual({ facility: null, reason: null, ambiguous: null, what: null });
    }
  });

  it("places nothing when two facilities list the number, and says why", () => {
    const both = [{ ...KC, accountNumbers: ["4417-2290-31"] }, { ...STL, accountNumbers: ["4417 2290 31"] }];
    const out = matchByIdentifier("4417-2290-31", null, both);
    expect(out.facility).toBeNull();
    expect(out.ambiguous).toBe("Account 4417-2290-31 is listed on two facilities");
  });

  it("never matches a number with fewer than four digits", () => {
    const short = [{ ...KC, accountNumbers: ["123"], meterNumbers: ["77"] }];
    expect(matchByIdentifier("123", "77", short).facility).toBeNull();
  });

  it("places nothing when the account and the meter number are on different facilities", () => {
    const apart = [{ ...KC, accountNumbers: ["4417-2290-31"] }, { ...STL, meterNumbers: ["E-55604"] }];
    expect(matchByIdentifier("4417-2290-31", "E 55604", apart).ambiguous).toBe(
      "Account 4417-2290-31 and meter E 55604 are listed on different facilities");
  });

  it("changes nothing for an old facility with no numbers", () => {
    expect(matchByIdentifier("4417-2290-31", "E-1", [KC, STL]).facility).toBeNull();
    expect(sharedNumbers([KC, STL])).toEqual([]);
  });
});

function Harness({ initial }: { initial: FacilityOption[] }) {
  const [engagement, setEngagement] = useState<EngagementConfig>({ ...engagementConfig, facilities: initial });
  return (
    <SetupScreen engagement={engagement} onChange={(patch) => setEngagement((e) => ({ ...e, ...patch }))}
      inScopeFields={[]} onInScopeChange={() => {}} />
  );
}

function paste(input: HTMLElement, text: string) {
  fireEvent.paste(input, { clipboardData: { getData: () => text } });
}

describe("Setup: account numbers on a facility", () => {
  it("takes a pasted list as chips, and removes one", () => {
    render(<Harness initial={[KC]} />);
    paste(screen.getByLabelText("Add account number"), "4417-2290-31, 55 0012;\nZürich-№ 7");
    const chips = screen.getByRole("list", { name: /Account numbers of Müller Käserei/ });
    expect(within(chips).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["4417-2290-31", "55 0012", "Zürich-№ 7"]);
    fireEvent.click(screen.getByRole("button", { name: "Remove account number 55 0012" }));
    expect(within(chips).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["4417-2290-31", "Zürich-№ 7"]);
  });

  it("adds a typed number on Enter and refuses a digit-free one in plain words", () => {
    render(<Harness initial={[KC]} />);
    const input = screen.getByLabelText("Add meter number");
    fireEvent.change(input, { target: { value: "E-55604" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("E-55604")).toBeTruthy();
    fireEvent.change(input, { target: { value: "Zürich" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("alert").textContent).toMatch(/needs at least one digit/);
    expect(screen.queryByRole("list", { name: /Meter numbers/ })?.textContent).toBe("E-55604");
  });

  it("notes a number listed on two facilities, and the note goes when one is removed", () => {
    render(<Harness initial={[{ ...KC, accountNumbers: ["4417-2290-31"] }, STL]} />);
    expect(screen.queryByText(/is on two facilities/)).toBeNull();
    const inputs = screen.getAllByLabelText("Add account number");
    paste(inputs[1], "4417 2290 31\n55-1");
    const note = "Account 4417-2290-31 is on two facilities. Bills with it won't be placed automatically.";
    expect(screen.getByText(note)).toBeTruthy();
    expect(sharedNumberNote({ kind: "account", value: "4417-2290-31", facilityIds: ["a", "b"] })).toBe(note);
    fireEvent.click(screen.getAllByRole("button", { name: "Remove account number 4417 2290 31" })[0]);
    expect(screen.queryByText(note)).toBeNull();
  });
});
