/* @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const server = vi.hoisted(() => ({
  trace: null as unknown,
  decisions: undefined as unknown,
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
      return { line_key: "k", trace: server.trace, ...(server.decisions ? { decisions: server.decisions } : {}) };
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
  const c = t.choices.find((x) => x.id === "equation:CO2")!; // the backend's trace already lists Eq. 1, 2 and 3
  const eq2 = c.options.find((o) => o.id === "eq_2")!;
  eq2.available = true;
  delete eq2.why_unavailable;
  c.options.find((o) => o.id === "eq_3")!.why_unavailable = "Needs an accepted carbon content.";
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
  server.decisions = undefined;
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

describe("pills follow the decision", () => {
  it("highlights the decided option and says it is recorded, while the trace still has the old one", async () => {
    const t = withEq2(base());
    t.choices.find((c) => c.id === "equation:CO2")!.decision = decision({ value: "eq_2", reason: "bill" });
    mount(t); // the mock never mutates: the backend has not applied it
    const group = await ready();
    expect(within(group).getByRole("button", { name: "Eq. 2" }).getAttribute("aria-pressed")).toBe("true");
    expect(within(group).getByRole("button", { name: "Eq. 1" }).getAttribute("aria-pressed")).toBe("false");
    expect(group.textContent).toContain("Chosen by Ada Reviewer");
    expect(group.textContent).toContain("Recorded. The total updates when the calculation is applied.");
  });

  it("shows no note when the decided option is the one the calculation used", async () => {
    const t = withEq2(base());
    t.choices.find((c) => c.id === "equation:CO2")!.decision = decision({ value: "eq_1" });
    mount(t);
    const group = await ready();
    expect(group.textContent).not.toContain("Recorded.");
  });
});

describe("typed numbers", () => {
  const openEdit = async (user: ReturnType<typeof userEvent.setup>) => {
    await efMenu(user);
    await user.click(screen.getByRole("menuitem", { name: "Edit" }));
    return screen.getByRole("textbox", { name: "Value: CO₂ emission factor" });
  };

  it("refuses an ambiguous comma, accepts thousands grouping", async () => {
    const user = userEvent.setup();
    mount(base());
    await ready();
    const value = await openEdit(user);
    await user.type(screen.getByRole("textbox", { name: "Reason: CO₂ emission factor" }), "why");
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    await user.clear(value);
    await user.type(value, "1,5");
    expect(screen.getByRole("alert").textContent).toBe("Use a point for decimals");
    expect(save.disabled).toBe(true);
    await user.clear(value);
    await user.type(value, "1,500.5");
    expect(screen.queryByRole("alert")).toBeNull();
    await user.click(save);
    await waitFor(() => expect(server.posts[0]?.body).toMatchObject({ action: "edit", value: 1500.5 }));
  });

  it("an input with no value on either side is still a number when it has a unit", async () => {
    const user = userEvent.setup();
    const t = base();
    t.inputs["ef.CO2"].recomputed = { value: null, unit: "kg/MMBtu", status: "not_reported" };
    delete t.inputs["ef.CO2"].company;
    mount(t);
    await ready();
    const value = await openEdit(user);
    expect((value as HTMLInputElement).value).toBe("");
    await user.type(value, "42.1");
    await user.type(screen.getByRole("textbox", { name: "Reason: CO₂ emission factor" }), "why");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(server.posts).toHaveLength(1));
    expect(server.posts[0].body).toEqual({ action: "edit", value: 42.1, unit: "kg/MMBtu", reason: "why" });
  });

  it("a 409 during an edit closes the editor, refetches, and keeps what was typed in the notice", async () => {
    const user = userEvent.setup();
    mount(base());
    await ready();
    const gets = server.gets;
    const value = await openEdit(user);
    await user.clear(value);
    await user.type(value, "42.1");
    await user.type(screen.getByRole("textbox", { name: "Reason: CO₂ emission factor" }), "why");
    server.postError = new ApiError(409, "Someone else decided.", {}, null);
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("status")).textContent).toContain("This value changed since you opened it (you entered 42.1)");
    expect(screen.queryByRole("textbox", { name: "Value: CO₂ emission factor" })).toBeNull();
    await waitFor(() => expect(server.gets).toBeGreaterThan(gets));
  });
});

describe("only decidable inputs offer actions", () => {
  it("offers a menu on the activity total and the factors, none on a GWP, and says why on the value", async () => {
    mount(base());
    await ready();
    expect(screen.getAllByRole("button", { name: /Actions for Activity data/ }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: /Actions for CO₂ emission factor/ }).length).toBeGreaterThan(0);
    expect(screen.queryAllByRole("button", { name: /Actions for CO₂ global warming potential/ })).toHaveLength(0);
    expect(screen.queryAllByRole("button", { name: /Actions for Unit conversion/ })).toHaveLength(0);
    const why = document.querySelector('[title^="Can\'t be changed: the GWP is chosen"]');
    expect(why).toBeTruthy();
  });

  it("offers nothing when the trace does not say decidable", async () => {
    const t = base();
    delete t.inputs["ef.CO2"].decidable;
    mount(t);
    await ready();
    expect(screen.queryAllByRole("button", { name: /Actions for CO₂ emission factor/ })).toHaveLength(0);
  });

  it("offers nothing on a mixed or blocked line, where every input says not decidable", async () => {
    const t = base();
    for (const input of Object.values(t.inputs)) {
      input.decidable = false;
      input.why_not = "this line mixes fuels or units: move the other records to their own line first";
    }
    mount(t);
    await ready();
    expect(screen.queryAllByRole("button", { name: /Actions for/ })).toHaveLength(0);
  });
});

describe("coded refusals", () => {
  const refuse = async (code: string | undefined) => {
    const user = userEvent.setup();
    const t = base();
    t.inputs["ef.CO2"].recomputed = { ...t.inputs["ef.CO2"].recomputed!, decision: decision({ value: 54.5 }) };
    mount(t);
    await ready();
    const gets = server.gets;
    server.postError = new ApiError(409, "server sentence", code ? { detail: "server sentence", code } : { detail: "server sentence" }, null);
    await efMenu(user);
    await user.click(screen.getByRole("menuitem", { name: "Revert" }));
    const text = (await screen.findByRole("status")).textContent ?? "";
    return { text, refetched: async () => server.gets > gets };
  };

  it.each(["mixed_line", "not_decidable", "no_working", "not_counted", "unit_mismatch", "invalid_value", "no_route", "a_future_code"])(
    "%s shows the backend's own sentence, not that the value changed",
    async (code) => {
      const { text } = await refuse(code);
      expect(text).toContain("server sentence");
      expect(text).not.toContain("changed since you opened");
      expect(onDecided).not.toHaveBeenCalled();
    },
  );

  it("stale says the automatic value moved and refetches", async () => {
    const { text } = await refuse("stale");
    expect(text).toContain("automatic value changed");
    await waitFor(() => expect(onDecided).toHaveBeenCalledTimes(1));
  });

  it("a 409 with no code is a change of state", async () => {
    const { text } = await refuse(undefined);
    expect(text).toContain("This value changed since you opened it");
    await waitFor(() => expect(onDecided).toHaveBeenCalledTimes(1));
  });
});

describe("decisions the working did not apply", () => {
  it("says so on the input, with the old and new automatic values for a stale one", async () => {
    const t = base();
    t.inputs["ef.CO2"].recomputed = { ...t.inputs["ef.CO2"].recomputed!, decision: decision({ value: 54.5 }) };
    server.decisions = {
      applied: [],
      not_applied: [
        { target: "input", id: "ef.CO2", side: "recomputed", status: "edited", reason: "stale", automatic_then: { value: 52, unit: "kg/MMBtu" }, automatic_now: { value: 53.06, unit: "kg/MMBtu" } },
        { target: "input", id: "ef.CH4", side: "recomputed", status: "edited", reason: "invalid_value", message: "Not applied: the value is not a number above 0." },
      ],
    };
    mount(t);
    await ready();
    const notes = screen.getAllByRole("status").map((n) => n.textContent);
    expect(notes).toContain("Your edit was made when the automatic value was 52 kg/MMBtu; it's now 53.06 kg/MMBtu, so it wasn't applied.");
    expect(notes).toContain("Your edit was not applied: the value is not a number above 0.");
  });

  it("says a stale choice with option names, and a decision whose target is gone on the line", async () => {
    const t = withEq2(base());
    server.decisions = {
      applied: [],
      not_applied: [
        { target: "choice", id: "equation:CO2", side: null, status: "edited", reason: "stale", automatic_then: "eq_1", automatic_now: "eq_2" },
        { target: "input", id: "gone.input", side: "recomputed", status: "edited", reason: "not_on_this_line", message: "This input is no longer part of the line's working." },
      ],
    };
    mount(t);
    await ready();
    const notes = screen.getAllByRole("status").map((n) => n.textContent);
    expect(notes).toContain("Your edit was made when the automatic value was Eq. 1; it's now Eq. 2, so it wasn't applied.");
    expect(notes).toContain("Your edit was not applied: This input is no longer part of the line's working.");
    // the one about a gone input is above the steps, not inside a pill group
    const line = notes.indexOf("Your edit was not applied: This input is no longer part of the line's working.");
    expect(within(screen.getByRole("group", { name: "CO2 equation" })).queryByText(/no longer part/)).toBeNull();
    expect(line).toBeGreaterThanOrEqual(0);
  });
});
