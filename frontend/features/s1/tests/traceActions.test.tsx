/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const server = vi.hoisted(() => ({
  trace: null as unknown,
  gets: 0,
  posts: [] as { path: string; body: unknown }[],
  postError: null as unknown,
  /** The trace the server answers with after a POST succeeds. */
  after: null as null | (() => unknown),
}));
vi.mock("../../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../../lib/api")>();
  return {
    ...actual,
    api: vi.fn(async (path: string, options?: { method?: string; body?: unknown }) => {
      if (options?.method === "POST") {
        server.posts.push({ path, body: options.body });
        if (server.postError) throw server.postError;
        if (server.after) server.trace = server.after();
        return {};
      }
      server.gets += 1;
      return { line_key: "k", trace: server.trace };
    }),
  };
});

import fixture from "../api/__fixtures__/calcTraceStationary.json";
import type { LineTrace, TraceDecision } from "../api/calcTrace";
import { ApiError } from "../../../lib/api";
import { TracePanel } from "../components/calc-trace/TracePanel";
import { TraceSection } from "../components/calc-trace/TraceSection";

const base = () => structuredClone(fixture) as unknown as LineTrace;
const decision = (over: Partial<TraceDecision>): TraceDecision => ({ status: "edited", by: "Ada Reviewer", at: "2026-11-26T10:00:00Z", ...over });
const totalOf = (t: LineTrace, value: number) => {
  t.steps.flatMap((s) => s.blocks).find((b) => b.id === "results.total")!.recomputed!.result.value = value;
  return t;
};
/** Equation choice CO2 with Eq. 2 available, so a reviewer can pick it. */
function withEq2(t: LineTrace): LineTrace {
  const c = t.choices.find((x) => x.id === "equation:CO2")!;
  c.options.push({ id: "eq_2", label: "Eq. 2", available: true, required_inputs: [] }, { id: "eq_3", label: "Eq. 3", available: false, why_unavailable: "Needs an accepted carbon content.", required_inputs: [] });
  return t;
}

const onDecided = vi.fn();
function mount(trace: LineTrace, version = "1") {
  server.trace = trace;
  return render(<TraceSection engagementId="E1" lineKey="k" version={version} onDecided={onDecided} fallback={<p>Summary numbers</p>} />);
}
const ready = () => screen.findByRole("group", { name: "CO2 equation" });
const efMenu = async (user: ReturnType<typeof userEvent.setup>) => {
  await user.click(screen.getAllByRole("button", { name: /Actions for CO₂ emission factor/ })[0]);
};

beforeEach(() => {
  server.gets = 0;
  server.posts = [];
  server.postError = null;
  server.after = null;
  onDecided.mockClear();
});
afterEach(cleanup);

describe("choice pills", () => {
  it("choosing Eq. 2 asks for a reason, posts choose, and shows the refetched total", async () => {
    const user = userEvent.setup();
    mount(withEq2(base()));
    const group = await ready();
    server.after = () => {
      const t = totalOf(withEq2(base()), 3500.5);
      t.choices.find((c) => c.id === "equation:CO2")!.chosen = "eq_2";
      t.choices.find((c) => c.id === "equation:CO2")!.chosen_by = "reviewer";
      return t;
    };
    await user.click(within(group).getByRole("button", { name: "Eq. 2" }));
    // not the automatic option: nothing is sent until a reason is given
    expect(server.posts).toHaveLength(0);
    const save = screen.getByRole("button", { name: "Use Eq. 2" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true);
    await user.type(screen.getByRole("textbox", { name: "Reason: CO2 equation" }), "Site heating value is on the bill");
    await user.click(save);
    await waitFor(() => expect(server.posts).toHaveLength(1));
    expect(server.posts[0]).toEqual({
      path: "/engagements/E1/calculation-lines/k/choices/equation%3ACO2",
      body: { action: "choose", option_id: "eq_2", reason: "Site heating value is on the bill" },
    });
    await waitFor(() => expect(screen.getByRole("table", { name: "Results · Line total" }).textContent).toContain("3,500.5"));
    expect(onDecided).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Summary numbers")).toBeNull(); // the panel stayed on screen while refetching
  });

  it("an unavailable option shows its reason and cannot be chosen", async () => {
    const user = userEvent.setup();
    const t = withEq2(base());
    mount(t);
    const group = await ready();
    const eq3 = within(group).getByRole("button", { name: /Eq\. 3/ });
    expect(eq3.getAttribute("aria-disabled")).toBe("true");
    expect(eq3.getAttribute("title")).toBe("Needs an accepted carbon content.");
    await user.click(eq3);
    expect(screen.queryByRole("textbox", { name: "Reason: CO2 equation" })).toBeNull();
    expect(server.posts).toHaveLength(0);
  });

  it("is reachable and operable from the keyboard", async () => {
    const user = userEvent.setup();
    mount(withEq2(base()));
    const group = await ready();
    const eq2 = within(group).getByRole("button", { name: "Eq. 2" });
    eq2.focus();
    expect(document.activeElement).toBe(eq2);
    await user.keyboard("{Enter}");
    const reason = screen.getByRole("textbox", { name: "Reason: CO2 equation" });
    expect(document.activeElement).toBe(reason);
    await user.keyboard("on the bill{Enter}");
    await waitFor(() => expect(server.posts).toHaveLength(1));
  });

  it("reverts a decided choice", async () => {
    const user = userEvent.setup();
    const t = withEq2(base());
    t.choices.find((c) => c.id === "equation:CO2")!.decision = decision({ value: "eq_2", reason: "bill" });
    mount(t);
    await ready();
    await user.click(screen.getByRole("button", { name: "Revert: CO2 equation" }));
    await waitFor(() => expect(server.posts).toHaveLength(1));
    expect(server.posts[0].body).toEqual({ action: "revert" });
  });

  it("shows a suggested option as a chip with Accept, and never as the chosen one", async () => {
    const user = userEvent.setup();
    const t = withEq2(base());
    t.choices.find((c) => c.id === "equation:CO2")!.suggestion = {
      origin: "ai", value: "eq_2", reason: "The bill prints a heating value.", quote: "HHV 1,037 Btu/cf", source: { kind: "document", document_id: "d1", file_name: "bill.pdf", page: 2 },
      model: "m", request_id: "r", suggested_at: "2026-11-26T10:00:00Z",
    };
    mount(t);
    const group = await ready();
    expect(within(group).getByRole("button", { name: /Suggested by Sustentra's AI/ })).toBeTruthy();
    expect(within(group).getByRole("button", { name: "Eq. 1" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(group).getByRole("button", { name: "Eq. 2" }).getAttribute("aria-pressed")).toBe("false");
    await user.click(screen.getByRole("button", { name: "Accept: CO2 equation" }));
    await waitFor(() => expect(server.posts[0]?.body).toEqual({ action: "accept" }));
  });
});

describe("recomputed inputs", () => {
  it("edits with a reason, keeps the unit fixed, and updates the cell and the totals", async () => {
    const user = userEvent.setup();
    mount(base());
    await ready();
    await efMenu(user);
    await user.click(screen.getByRole("menuitem", { name: "Edit" }));
    const value = screen.getByRole("textbox", { name: "Value: CO₂ emission factor" });
    expect((value as HTMLInputElement).value).toBe("53.06");
    expect(screen.getAllByText("kg/MMBtu").length).toBeGreaterThan(0); // the unit is text, not a field
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    await user.clear(value);
    await user.type(value, "abc");
    await user.type(screen.getByRole("textbox", { name: "Reason: CO₂ emission factor" }), "Supplier certificate");
    expect(save.disabled).toBe(true); // not a number
    await user.clear(value);
    await user.type(value, "54.5");
    expect(save.disabled).toBe(false);
    server.after = () => {
      const t = totalOf(base(), 3600.25);
      t.inputs["ef.CO2"].recomputed = { ...t.inputs["ef.CO2"].recomputed!, value: 54.5, status: "edited", decision: decision({ value: 54.5, unit: "kg/MMBtu", reason: "Supplier certificate" }) };
      const op = t.steps.flatMap((s) => s.blocks).find((b) => b.id === "emissions.CO2")!.recomputed!.terms[1].operand;
      op.value = 54.5;
      return t;
    };
    await user.click(save);
    await waitFor(() => expect(server.posts).toHaveLength(1));
    expect(server.posts[0]).toEqual({
      path: "/engagements/E1/calculation-lines/k/inputs/ef.CO2/recomputed",
      body: { action: "edit", value: 54.5, unit: "kg/MMBtu", reason: "Supplier certificate" },
    });
    await waitFor(() => expect(screen.getByRole("table", { name: "Results · Line total" }).textContent).toContain("3,600.25"));
    const row = within(screen.getByRole("table", { name: "Step 3 · Emissions per gas · CO₂" })).getAllByRole("row").find((r) => r.textContent?.startsWith("Recomputed"))!;
    expect(row.textContent).toContain("54.5 kg/MMBtu");
    const mark = within(row).getByText("Edited");
    expect(mark.getAttribute("title")).toBe("Edited by Ada Reviewer: Supplier certificate");
    expect(onDecided).toHaveBeenCalledTimes(1);
  });

  it("an edit needs a reason: the server's 422 sentence shows beside the field and nothing refetches", async () => {
    const user = userEvent.setup();
    mount(base());
    await ready();
    const gets = server.gets;
    await efMenu(user);
    await user.click(screen.getByRole("menuitem", { name: "Edit" }));
    await user.type(screen.getByRole("textbox", { name: "Reason: CO₂ emission factor" }), "x");
    server.postError = new ApiError(422, "'CO₂ emission factor (recomputed)': enter a number.", null, null);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toContain("enter a number");
    expect(server.gets).toBe(gets);
    expect(onDecided).not.toHaveBeenCalled();
  });

  it("rejects with a reason and shows the automatic value struck through", async () => {
    const user = userEvent.setup();
    mount(base());
    await ready();
    await efMenu(user);
    await user.click(screen.getByRole("menuitem", { name: "Reject" }));
    await user.type(screen.getByRole("textbox", { name: "Reason: CO₂ emission factor" }), "Wrong fuel");
    server.after = () => {
      const t = base();
      t.inputs["ef.CO2"].recomputed = { ...t.inputs["ef.CO2"].recomputed!, decision: decision({ status: "rejected", value: null, reason: "Wrong fuel" }) };
      return t;
    };
    await user.click(screen.getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(server.posts[0]?.body).toEqual({ action: "reject", reason: "Wrong fuel" }));
    await waitFor(() => expect(document.querySelector(".s1-cp-decided .is-rejected")).toBeTruthy());
    expect(document.querySelector(".is-rejected")!.textContent).toContain("53.06 kg/MMBtu");
  });

  it("reverts a decided input, and offers Revert (not Reject) only then", async () => {
    const user = userEvent.setup();
    const t = base();
    t.inputs["ef.CO2"].recomputed = { ...t.inputs["ef.CO2"].recomputed!, status: "edited", decision: decision({ value: 54.5 }) };
    mount(t);
    await ready();
    await efMenu(user);
    expect(screen.queryByRole("menuitem", { name: "Reject" })).toBeNull();
    await user.click(screen.getByRole("menuitem", { name: "Revert" }));
    await waitFor(() => expect(server.posts).toHaveLength(1));
    expect(server.posts[0].body).toEqual({ action: "revert" });
  });

  it("marks an accepted input with a quiet check", async () => {
    const t = base();
    t.inputs["ef.CO2"].recomputed = { ...t.inputs["ef.CO2"].recomputed!, decision: decision({ status: "accepted", value: 53.06 }) };
    mount(t);
    await ready();
    expect(screen.getAllByRole("img", { name: "Accepted by Ada Reviewer" }).length).toBeGreaterThan(0);
  });

  it("opens the menu from the keyboard and walks it with the arrow keys", async () => {
    const user = userEvent.setup();
    mount(base());
    await ready();
    const trigger = screen.getAllByRole("button", { name: /Actions for CO₂ emission factor/ })[0];
    trigger.focus();
    await user.keyboard("{Enter}");
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((i) => i.textContent)).toEqual(["Edit", "Reject"]);
    expect(document.activeElement).toBe(items[0]);
    await user.keyboard("{ArrowDown}");
    expect(document.activeElement).toBe(items[1]);
    await user.keyboard("{Escape}");
    expect(document.activeElement).toBe(trigger);
  });
});

describe("pending suggestions", () => {
  it("never show on the recomputed side, and a company-side suggestion is marked as the AI's", async () => {
    const t = base();
    const suggestion = { origin: "ai" as const, value: 77.77, unit: "kg/MMBtu", reason: "Printed on the bill", quote: "77.77", source: { kind: "document" as const, document_id: "d1" }, model: "m", request_id: "r", suggested_at: "2026-11-26T10:00:00Z" };
    t.inputs["ef.CO2"].recomputed = { ...t.inputs["ef.CO2"].recomputed!, suggestion };
    t.inputs["ef.CH4"].company = { ...t.inputs["ef.CH4"].company!, status: "suggested", suggestion: { ...suggestion, value: 2.5 } };
    mount(t);
    await ready();
    expect(document.body.textContent).not.toContain("77.77");
    const rec = within(screen.getByRole("table", { name: "Step 3 · Emissions per gas · CO₂" })).getAllByRole("row").find((r) => r.textContent?.startsWith("Recomputed"))!;
    expect(within(rec).queryByText(/Suggested by Sustentra's AI/)).toBeNull();
    const co = within(screen.getByRole("table", { name: "Step 3 · Emissions per gas · CH₄" })).getAllByRole("row").find((r) => r.textContent?.startsWith("Company"))!;
    expect(within(co).getByText("Suggested by Sustentra's AI")).toBeTruthy();
  });
});

describe("errors stay in the panel", () => {
  it("a 409 refetches and says the value changed", async () => {
    const user = userEvent.setup();
    const t = withEq2(base());
    t.choices.find((c) => c.id === "equation:CO2")!.decision = decision({ value: "eq_2" });
    mount(t);
    await ready();
    const gets = server.gets;
    server.postError = new ApiError(409, "'CO2 equation' is already pending, so there is nothing to revert.", null, null);
    await user.click(screen.getByRole("button", { name: "Revert: CO2 equation" }));
    expect((await screen.findByRole("status")).textContent).toContain("This value changed since you opened it");
    await waitFor(() => expect(server.gets).toBeGreaterThan(gets));
    expect(onDecided).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("group", { name: "CO2 equation" })).toBeTruthy();
  });

  it("a 403 hides every action", async () => {
    const user = userEvent.setup();
    mount(withEq2(base()));
    const group = await ready();
    server.postError = new ApiError(403, "Forbidden", null, null);
    await user.click(within(group).getByRole("button", { name: "Eq. 2" }));
    await user.type(screen.getByRole("textbox", { name: "Reason: CO2 equation" }), "why");
    await user.click(screen.getByRole("button", { name: "Use Eq. 2" }));
    expect((await screen.findByRole("alert")).textContent).toContain("view this calculation but not change it");
    expect(screen.queryAllByRole("button", { name: /Actions for/ })).toHaveLength(0);
    expect(within(screen.getByRole("group", { name: "CO2 equation" })).queryAllByRole("button")).toHaveLength(0);
  });

  it("a network error is shown in the panel and the rest of the panel stays", async () => {
    const user = userEvent.setup();
    const t = base();
    t.inputs["ef.CO2"].recomputed = { ...t.inputs["ef.CO2"].recomputed!, decision: decision({ value: 54.5 }) };
    mount(t);
    await ready();
    server.postError = new Error("Failed to fetch");
    await efMenu(user);
    await user.click(screen.getByRole("menuitem", { name: "Revert" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Not saved");
    expect(document.querySelector(".s1-cp-trace")!.parentElement!.contains(alert)).toBe(true);
    expect(screen.getByRole("table", { name: "Results · Line total" })).toBeTruthy();
  });
});

describe("a read-only panel", () => {
  it("draws no action and plain pills when nothing provides actions", () => {
    render(<TracePanel trace={withEq2(base())} />);
    expect(screen.queryAllByRole("button", { name: /Actions for/ })).toHaveLength(0);
    const group = screen.getByRole("group", { name: "CO2 equation" });
    expect(within(group).queryAllByRole("button")).toHaveLength(0);
    fireEvent.click(within(group).getByText("Eq. 2"));
    expect(server.posts).toHaveLength(0);
  });
});

describe("a role that cannot decide", () => {
  it("renders the decision states but no action menu, pill button or Revert from the start", async () => {
    const t = withEq2(base());
    t.inputs["ef.CO2"].recomputed = { ...t.inputs["ef.CO2"].recomputed!, status: "edited", decision: decision({ value: 54.5 }) };
    t.choices.find((c) => c.id === "equation:CO2")!.decision = decision({ value: "eq_2" });
    server.trace = t;
    render(<TraceSection engagementId="E1" lineKey="k" version="1" canDecide={false} fallback={<p>Summary numbers</p>} />);
    const group = await ready();
    expect(screen.getAllByText("Edited").length).toBeGreaterThan(0);
    expect(screen.queryAllByRole("button", { name: /Actions for/ })).toHaveLength(0);
    expect(within(group).queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryByRole("button", { name: /Revert/ })).toBeNull();
  });
});
