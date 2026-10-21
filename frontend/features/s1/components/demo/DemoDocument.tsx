"use client";

import { useEffect, useRef, type ReactNode } from "react";

import type { EngagementConfig } from "../../types";
import type { ReviewValue } from "../../types/review";

/**
 * A demo document drawn whole, as the client sent it: every page, every line, with each
 * value the reading took from it highlighted in place. Values the reading could not find
 * are marked where they belong. Clicking a highlight selects its value (the review cards
 * scroll to it); selecting a card scrolls the document to its highlight.
 */
export function DemoDocument({
  values,
  engagement,
  selectedId,
  onPick,
}: {
  /** Every value read from this one document. */
  values: ReviewValue[];
  engagement: EngagementConfig;
  selectedId: string | null;
  /** The values behind a clicked highlight (several when one figure feeds two values). */
  onPick: (ids: string[]) => void;
}) {
  const root = useRef<HTMLDivElement>(null);

  // Bring the selected value's highlight into view, inside the source pane only.
  useEffect(() => {
    if (!selectedId || !root.current) return;
    const el = root.current.querySelector<HTMLElement>(`[data-ids~="${CSS.escape(selectedId)}"]`);
    const scroller = root.current.closest<HTMLElement>(".s1-xr-src-body");
    if (!el || !scroller) return;
    const box = el.getBoundingClientRect();
    const view = scroller.getBoundingClientRect();
    if (box.top >= view.top + 40 && box.bottom <= view.bottom - 40) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    scroller.scrollTo({
      top: scroller.scrollTop + (box.top - view.top) - view.height / 2 + box.height / 2,
      behavior: reduce ? "auto" : "smooth",
    });
  }, [selectedId]);

  if (!values.length) return null;
  const first = values[0];
  const ctx: Ctx = { values, engagement, selectedId, onPick };
  const missing = values.filter(isMissing).length;

  return (
    <div className="s1-dd" ref={root}>
      <div className="s1-dd-legend" aria-label="Highlights on this document">
        <span>
          <strong>{values.length}</strong> {values.length === 1 ? "value" : "values"} read
          {missing ? (
            <>
              {" · "}
              <strong className="s1-dd-legend__miss">{missing} not found</strong>
            </>
          ) : null}
        </span>
        <span className="s1-dd-key s1-dd-key--to_review">To review</span>
        <span className="s1-dd-key s1-dd-key--accepted">Accepted</span>
        <span className="s1-dd-key s1-dd-key--corrected">Corrected</span>
        <span className="s1-dd-key s1-dd-key--missing">Not found</span>
      </div>
      {first.documentType === "Electricity bill" ? (
        <UtilityBill ctx={ctx} kind="electricity" />
      ) : first.documentType === "Natural gas bill" ? (
        <UtilityBill ctx={ctx} kind="gas" />
      ) : /refrigerant/i.test(first.documentType) ? (
        <ServiceTicket ctx={ctx} />
      ) : first.sourceKind === "image" ? (
        <Photo ctx={ctx} />
      ) : first.sourceKind === "spreadsheet" ? (
        <Sheet ctx={ctx} />
      ) : first.sourceKind === "text" ? (
        <Letter ctx={ctx} />
      ) : first.documentType === "Emission factor source list" ? (
        <FactorList ctx={ctx} />
      ) : (
        <Statement ctx={ctx} />
      )}
    </div>
  );
}

/* ================================ highlight ================================ */

interface Ctx {
  values: ReviewValue[];
  engagement: EngagementConfig;
  selectedId: string | null;
  onPick: (ids: string[]) => void;
}

function isMissing(v: ReviewValue): boolean {
  return Boolean(v.missing) || v.value === "not found";
}

const STATE_ORDER = ["missing", "to_review", "requested", "corrected", "accepted"] as const;

function stateOf(vs: ReviewValue[]): (typeof STATE_ORDER)[number] {
  const states = vs.map((v) => (isMissing(v) ? "missing" : v.reviewState));
  return STATE_ORDER.find((s) => states.includes(s)) ?? "to_review";
}

/** A figure on the page that the reading took one or more values from. */
function Hl({ ctx, vs, children }: { ctx: Ctx; vs: ReviewValue[]; children?: ReactNode }) {
  if (!vs.length) return <>{children}</>;
  const ids = vs.map((v) => v.id);
  const state = stateOf(vs);
  const selected = ctx.selectedId !== null && ids.includes(ctx.selectedId);
  const label = vs.map((v) => v.whatItIs).join(" · ");
  return (
    <button
      type="button"
      className={`s1-dd-hl s1-dd-hl--${state}${selected ? " is-sel" : ""}`}
      data-ids={ids.join(" ")}
      title={state === "missing" ? `${label}: not found on the document` : label}
      aria-label={`${label}${state === "missing" ? ", not found" : ""}`}
      aria-pressed={selected}
      onClick={() => ctx.onPick(ids)}
    >
      {children ?? (state === "missing" ? "Not found" : `${vs[0].value}${vs[0].unit ? ` ${vs[0].unit}` : ""}`)}
    </button>
  );
}

const pick = (ctx: Ctx, re: RegExp) => ctx.values.filter((v) => re.test(v.whatItIs));
const rest = (ctx: Ctx, used: ReviewValue[]) => ctx.values.filter((v) => !used.includes(v));

/* ================================ helpers ================================ */

function seed(text: string): number {
  let h = 2166136261;
  for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return Math.abs(h);
}

function num(text: string | undefined): number | null {
  if (!text) return null;
  const n = Number(text.replace(/[^0-9.]/g, ""));
  return Number.isFinite(n) && n > 0 ? n : null;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function periodOf(period: string): { start: string; end: string; days: number; month: number; year: number } {
  const match = /([A-Z][a-z]{2})\s+(\d{4})/.exec(period);
  const month = match ? Math.max(0, MONTHS.indexOf(match[1])) : 0;
  const year = match ? Number(match[2]) : 2025;
  const days = new Date(year, month + 1, 0).getDate();
  const name = MONTHS[month];
  return { start: `01 ${name} ${year}`, end: `${days} ${name} ${year}`, days, month, year };
}

function fmt(n: number, digits = 0): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function facilityOf(ctx: Ctx): { name: string; address: string } {
  const id = ctx.values[0].facilityId;
  const facility = ctx.engagement.facilities.find((f) => f.facilityId === id);
  return { name: facility?.name ?? "Cascade Provisions Co.", address: facility?.address ?? "Corporate office" };
}

function Page({ n, of, children, tone }: { n: number; of: number; children: ReactNode; tone?: string }) {
  return (
    <section className={`s1-dd-page${tone ? ` s1-dd-page--${tone}` : ""}`} aria-label={`Page ${n} of ${of}`}>
      {children}
      <footer className="s1-dd-foot">Page {n} of {of}</footer>
    </section>
  );
}

function Row({ label, children, strong }: { label: ReactNode; children: ReactNode; strong?: boolean }) {
  return (
    <div className={`s1-dd-row${strong ? " s1-dd-row--strong" : ""}`}>
      <span>{label}</span>
      <span>{children}</span>
    </div>
  );
}

/* ============================== utility bill ============================== */

const BRANDS: Record<string, Record<string, string>> = {
  electricity: {
    "facility-tualatin": "Willamette Valley Power",
    "facility-kent": "Pacific Grid Electric",
    "facility-modesto": "Central Valley Electric",
  },
  gas: {
    "facility-tualatin": "Northwest Gas Service",
    "facility-kent": "Northwest Gas Service",
    "facility-modesto": "Valley Gas Company",
  },
};

function UtilityBill({ ctx, kind }: { ctx: Ctx; kind: "electricity" | "gas" }) {
  const first = ctx.values[0];
  const s = seed(first.documentId);
  const facility = facilityOf(ctx);
  const brand = BRANDS[kind][first.facilityId ?? ""] ?? (kind === "electricity" ? "Pacific Grid Electric" : "Northwest Gas Service");
  const period = periodOf(first.period);
  const consumption = pick(ctx, /consumed/i);
  const peak = pick(ctx, /peak demand/i);
  const periodEnd = pick(ctx, /service period end/i);
  const others = rest(ctx, [...consumption, ...peak, ...periodEnd]);
  const unit = kind === "electricity" ? "kWh" : "therms";
  const qty = num(consumption[0]?.value) ?? (kind === "electricity" ? 380000 + (s % 90000) : 22000 + (s % 9000));
  const previous = 1_000_000 + (s % 400_000);
  const rate = kind === "electricity" ? 0.112 : 1.18;
  const energy = qty * rate;
  const demandKw = num(peak[0]?.value) ?? Math.round(qty / 410);
  const demandCharge = kind === "electricity" ? demandKw * 6.25 : 0;
  const fixed = kind === "electricity" ? 1845.75 : 312.4;
  const tax = (energy + demandCharge + fixed) * 0.031;
  const total = energy + demandCharge + fixed + tax;
  const invoice = `${kind === "electricity" ? "E" : "G"}-${period.year}-${String(period.month + 1).padStart(2, "0")}-${String(s % 90000).padStart(5, "0")}`;
  const statementDate = `${String(5 + (s % 9)).padStart(2, "0")} ${MONTHS[(period.month + 1) % 12]} ${period.month === 11 ? period.year + 1 : period.year}`;
  const history = Array.from({ length: 12 }, (_, i) => 0.7 + ((seed(`${first.documentId}${i}`) % 40) / 100));

  return (
    <>
      <Page n={1} of={2}>
        <header className={`s1-dd-band s1-dd-band--${kind}`}>
          <div>
            <strong>{brand}</strong>
            <span>{kind === "electricity" ? "Commercial electricity statement" : "Commercial natural gas statement"}</span>
          </div>
          <div className="s1-dd-band__meta">
            <span>Invoice {invoice}</span>
            <span>Statement date {statementDate}</span>
          </div>
        </header>
        <div className="s1-dd-two">
          <div>
            <div className="s1-dd-label">Service account</div>
            <div className="s1-dd-big">Cascade Provisions Co.</div>
            <div>{facility.name}</div>
            <div className="s1-dd-dim">{facility.address}</div>
            <div className="s1-dd-dim">
              Account {String(4400000 + (s % 99999))} · Rate {kind === "electricity" ? "E-19 Commercial" : "G-NR1 Large commercial"}
            </div>
          </div>
          <div className="s1-dd-right">
            <div className="s1-dd-label">Service period</div>
            <div className="s1-dd-big">
              {period.start} –{" "}
              {periodEnd.length ? <Hl ctx={ctx} vs={periodEnd}>not printed</Hl> : period.end}
            </div>
            <div className="s1-dd-dim">Billing days {period.days}</div>
          </div>
        </div>

        <h4 className="s1-dd-h">Meter readings · Meter {kind === "electricity" ? "E" : "G"}{String(s % 9000).padStart(4, "0")}</h4>
        <Row label={`Previous read (${period.start})`}>{fmt(previous)} {kind === "electricity" ? "kWh" : "ccf"}</Row>
        <Row label={`Current read (${period.end})`}>
          {fmt(previous + (kind === "electricity" ? qty : qty * 0.97))} {kind === "electricity" ? "kWh" : "ccf"}
        </Row>
        <Row label="Multiplier">1.000</Row>

        <h4 className="s1-dd-h">Usage this period</h4>
        <Row label={kind === "electricity" ? "Electricity delivered" : "Natural gas used"} strong>
          {consumption.length ? <Hl ctx={ctx} vs={consumption} /> : `${fmt(qty)} ${unit}`}
        </Row>
        {kind === "electricity" ? (
          <>
            <Row label="Peak demand">{peak.length ? <Hl ctx={ctx} vs={peak} /> : `${fmt(demandKw)} kW`}</Row>
            <Row label="Power factor">0.96</Row>
          </>
        ) : (
          <>
            <Row label="Therm factor">1.037</Row>
            <Row label="Heat content">{fmt(qty / 10, 1)} MMBtu</Row>
          </>
        )}
        {others.map((v) => (
          <Row key={v.id} label={v.whatItIs}>
            <Hl ctx={ctx} vs={[v]} />
          </Row>
        ))}

        <h4 className="s1-dd-h">Charges</h4>
        <Row label={`${kind === "electricity" ? "Energy" : "Gas supply"} (${fmt(qty)} ${unit} × $${rate.toFixed(3)})`}>${fmt(energy, 2)}</Row>
        {kind === "electricity" ? <Row label={`Demand (${fmt(demandKw)} kW × $6.25)`}>${fmt(demandCharge, 2)}</Row> : null}
        <Row label="Basic service charge">${fmt(fixed, 2)}</Row>
        <Row label="State and local taxes">${fmt(tax, 2)}</Row>
        <Row label="Amount due" strong>
          ${fmt(total, 2)}
        </Row>
      </Page>

      <Page n={2} of={2}>
        <h4 className="s1-dd-h">Your usage, last 12 months</h4>
        <div className="s1-dd-bars" aria-hidden>
          {history.map((h, i) => (
            <span key={i} style={{ height: `${Math.round(h * 100)}%` }} className={i === 11 ? "is-now" : undefined} />
          ))}
        </div>
        <div className="s1-dd-barlabels" aria-hidden>
          {Array.from({ length: 12 }, (_, i) => (
            <span key={i}>{MONTHS[(period.month + 1 + i) % 12]}</span>
          ))}
        </div>
        <h4 className="s1-dd-h">Messages</h4>
        <p className="s1-dd-p">
          {kind === "electricity"
            ? "Your rate schedule includes a demand charge based on the highest 15-minute load in the period. Shifting large loads outside 4–9 pm can lower it."
            : "Gas use is billed in therms. One therm is 100,000 Btu; the therm factor converts the volume read at the meter to its heat content."}
        </p>
        <div className="s1-dd-stub">
          <div>
            <div className="s1-dd-label">Remittance</div>
            <div>{brand}</div>
            <div className="s1-dd-dim">Account {String(4400000 + (s % 99999))}</div>
          </div>
          <div className="s1-dd-right">
            <div className="s1-dd-label">Amount due</div>
            <div className="s1-dd-big">${fmt(total, 2)}</div>
          </div>
        </div>
      </Page>
    </>
  );
}

/* ============================ refrigerant ticket ============================ */

function ServiceTicket({ ctx }: { ctx: Ctx }) {
  const first = ctx.values[0];
  const s = seed(first.documentId);
  const facility = facilityOf(ctx);
  const added = pick(ctx, /added/i);
  const recovered = pick(ctx, /recovered/i);
  const others = rest(ctx, [...added, ...recovered]);
  return (
    <Page n={1} of={1}>
      <header className="s1-dd-band s1-dd-band--service">
        <div>
          <strong>Coastal Refrigeration Services</strong>
          <span>Commercial refrigeration · service ticket</span>
        </div>
        <div className="s1-dd-band__meta">
          <span>Ticket CRS-{String(s % 90000).padStart(5, "0")}</span>
          <span>Service date 14 Nov 2025</span>
        </div>
      </header>
      <div className="s1-dd-two">
        <div>
          <div className="s1-dd-label">Site</div>
          <div className="s1-dd-big">Cascade Provisions Co. · {facility.name}</div>
          <div className="s1-dd-dim">{facility.address}</div>
        </div>
        <div className="s1-dd-right">
          <div className="s1-dd-label">Technician</div>
          <div>J. Alvarez · EPA 608 Type II</div>
          <div className="s1-dd-dim">Cert. 608-{String(s % 900000).padStart(6, "0")}</div>
        </div>
      </div>
      <h4 className="s1-dd-h">Refrigerant handled</h4>
      <div className="s1-dd-table s1-dd-table--4">
        <span>Unit</span>
        <span>Refrigerant</span>
        <span>Charge added</span>
        <span>Recovered</span>
        <span>RTU-3 · rooftop unit</span>
        <span>R-404A</span>
        <span>{added.length ? <Hl ctx={ctx} vs={added} /> : "0 kg"}</span>
        <span>
          {recovered.length ? (
            <Hl ctx={ctx} vs={recovered}>
              {recovered[0].value === "n/a" ? <span className="s1-dd-smudge">illegible</span> : undefined}
            </Hl>
          ) : (
            "0 kg"
          )}
        </span>
        <span>WIC-1 · walk-in cooler</span>
        <span>R-404A</span>
        <span>0 kg</span>
        <span>0 kg</span>
      </div>
      {others.map((v) => (
        <Row key={v.id} label={v.whatItIs}>
          <Hl ctx={ctx} vs={[v]} />
        </Row>
      ))}
      <h4 className="s1-dd-h">Work performed</h4>
      <p className="s1-dd-p">
        Leak found at the RTU-3 liquid-line service valve; valve core replaced, system evacuated and recharged. Standing
        pressure test held for 30 minutes. Recovered refrigerant returned to cylinder CRS-C-118.
      </p>
      <div className="s1-dd-sign">
        <span>Technician signature: J. Alvarez</span>
        <span>Customer: D. Whitfield</span>
      </div>
    </Page>
  );
}

/* ================================== photo ================================== */

function Photo({ ctx }: { ctx: Ctx }) {
  const first = ctx.values[0];
  const s = seed(first.documentId);
  const meter = first.documentType === "Meter reading or meter photo";
  return (
    <section className="s1-dd-photo" aria-label="Photo">
      <div className="s1-dd-photo__meta">
        <span>{first.filename}</span>
        <span>4032 × 3024 · taken 31 Dec 2025, 07:42</span>
      </div>
      <div className={`s1-dd-photo__frame${meter ? "" : " s1-dd-photo__frame--note"}`}>
        {meter ? (
          <div className="s1-dd-meter">
            <div className="s1-dd-meter__brand">ELSTER A3 · kWh</div>
            <div className="s1-dd-meter__lcd">
              {ctx.values.map((v) => (
                <Hl key={v.id} ctx={ctx} vs={[v]}>
                  {v.value}
                </Hl>
              ))}
            </div>
            <div className="s1-dd-meter__id">Meter E{String(s % 9000).padStart(4, "0")} · CL200 · 240 V</div>
          </div>
        ) : (
          <div className="s1-dd-note">
            <div>Gas meter — basement</div>
            <div>
              read{" "}
              {ctx.values.map((v) => (
                <Hl key={v.id} ctx={ctx} vs={[v]}>
                  {v.value}
                </Hl>
              ))}
            </div>
            <div>12/31 — DW</div>
          </div>
        )}
      </div>
    </section>
  );
}

/* ================================== sheet ================================== */

interface SheetLayout {
  columns: string[];
  rows: string[][];
}

function sheetLayout(ctx: Ctx): SheetLayout {
  const first = ctx.values[0];
  if (first.documentId === "DOC-WORKBOOK") {
    const rows: string[][] = [
      ["Cascade Provisions Co. · GHG inventory FY2025", "", "", "", ""],
      ["", "", "", "", ""],
      ["Organizational boundary approach", "", "", "", ""],
      ["Reporting year", "2025", "", "", ""],
      ["GWP set", "IPCC AR5", "", "", ""],
      ["", "", "", "", ""],
      ["Scope 1", "Activity", "Quantity", "tCO₂e", "Source"],
      ["Stationary combustion", "Natural gas", "1,221,600 therms", "9,561", "Monthly gas bills"],
      ["Stationary combustion", "Propane", "18,900 gal", "115", "Delivery tickets"],
      ["Mobile combustion", "Diesel", "468,000 gal", "4,617", "Fleet fuel cards"],
      ["Fugitive emissions", "R-404A", "601 kg", "2,366", "Service logs"],
      ["Total Scope 1", "", "", "", "Client calculation"],
      ["", "", "", "", ""],
      ["Stationary combustion subtotal", "", "", "", ""],
      ["", "", "", "", ""],
      ["Scope 2", "Activity", "Quantity", "tCO₂e", "Source"],
      ["Electricity · Tualatin", "Grid (NWPP)", "5,140,000 kWh", "1,830", "Monthly bills"],
      ["Electricity · Kent", "Grid (NWPP)", "6,220,000 kWh", "2,213", "Monthly bills"],
      ["Electricity · Modesto", "Grid (CAMX)", "7,310,000 kWh", "2,132", "Monthly bills"],
      ["Total Scope 2, location-based", "", "", "", "Client calculation"],
      ["Total Scope 2, market-based", "", "", "", "With RECs retired"],
      ["", "", "", "", ""],
      ["Prepared by", "Dana Whitfield", "", "", "Feb 2026"],
    ];
    return { columns: ["A", "B", "C", "D", "E"], rows };
  }
  if (first.documentId === "DOC-MILEAGE") {
    const rows = [["Date", "Trip", "Miles claimed", "Rate", "Amount"]];
    for (let i = 1; i <= 312; i += 1) {
      const miles = 18 + ((i * 7) % 140);
      const day = new Date(2025, 0, 1 + Math.floor((i * 365) / 313));
      rows.push([
        day.toLocaleDateString("en-US", { month: "short", day: "2-digit" }),
        `Trip ${String(i).padStart(3, "0")}`,
        String(miles),
        "$0.67",
        `$${(miles * 0.67).toFixed(2)}`,
      ]);
    }
    return { columns: ["A", "B", "C", "D", "E"], rows };
  }
  if (first.documentId === "DOC-ROSTER") {
    const categories = ["Packaging", "Ingredients", "Logistics", "Maintenance", "IT services", "Cleaning", "Utilities"];
    const rows = [["Supplier ID", "Supplier", "Category", "State", "Annual spend"]];
    for (let i = 1; i <= 218; i += 1) {
      rows.push([
        `SUP-${String(i).padStart(4, "0")}`,
        `Supplier ${String(i).padStart(3, "0")}`,
        categories[i % categories.length],
        ["OR", "WA", "CA", "ID", "NV"][i % 5],
        `$${((12 + ((i * 13) % 900)) * 1000).toLocaleString()}`,
      ]);
    }
    return { columns: ["A", "B", "C", "D", "E"], rows };
  }
  // Any other sheet: one row per value, the value in column C.
  const rows = [["Item", "Period", "Value", "Unit", "Note"]];
  ctx.values.forEach((v) => rows.push([v.whatItIs, v.period, v.value, v.unit, ""]));
  return { columns: ["A", "B", "C", "D", "E"], rows };
}

function Sheet({ ctx }: { ctx: Ctx }) {
  const first = ctx.values[0];
  const layout = sheetLayout(ctx);
  const byCell = new Map<string, ReviewValue[]>();
  ctx.values.forEach((v, i) => {
    const cell = v.cell ?? `C${i + 2}`;
    byCell.set(cell, [...(byCell.get(cell) ?? []), v]);
  });
  return (
    <section className="s1-dd-sheet" aria-label="Spreadsheet">
      <div className="s1-dd-sheet__bar">
        <span className="s1-dd-sheet__tab">{first.sheet ?? "Sheet1"}</span>
        <span>{first.filename}</span>
      </div>
      <div className="s1-dd-sheet__scroll">
        <table>
          <thead>
            <tr>
              <th />
              {layout.columns.map((c) => (
                <th key={c}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {layout.rows.map((row, r) => (
              <tr key={r} className={r === 0 ? "is-title" : undefined}>
                <th>{r + 1}</th>
                {layout.columns.map((c, ci) => {
                  const vs = byCell.get(`${c}${r + 1}`) ?? [];
                  return (
                    <td key={c}>
                      {vs.length ? <Hl ctx={ctx} vs={vs}>{vs[0].value}</Hl> : row[ci]}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/* ================================== letter ================================== */

function Letter({ ctx }: { ctx: Ctx }) {
  const first = ctx.values[0];
  return (
    <Page n={1} of={1} tone="letter">
      <div className="s1-dd-letterhead">
        <strong>Cascade Provisions Co.</strong>
        <span>1200 Industrial Way, Tualatin, OR 97062</span>
      </div>
      <h3 className="s1-dd-title">{first.documentType} · FY2025</h3>
      <p className="s1-dd-p">
        This statement sets out the organizational boundary used for Cascade Provisions Co.&rsquo;s greenhouse gas
        inventory for the year ended 31 December 2025, prepared under the GHG Protocol Corporate Standard.
      </p>
      {ctx.values.map((v) => (
        <p key={v.id} className="s1-dd-p">
          <Hl ctx={ctx} vs={[v]}>
            {(v.snippet ?? v.value).replace(/^[“"]|[”"]$/g, "")}
          </Hl>
        </p>
      ))}
      <p className="s1-dd-p">
        The boundary includes the Tualatin Plant, the Kent Cannery and Modesto Bottling, each wholly owned and operated
        by the company. Leased office space in Portland is excluded as immaterial (below 0.5% of estimated emissions).
      </p>
      <div className="s1-dd-sign">
        <span>Dana Whitfield, Director of Sustainability</span>
        <span>18 Feb 2026</span>
      </div>
    </Page>
  );
}

/* =============================== factor list =============================== */

function FactorList({ ctx }: { ctx: Ctx }) {
  const grid = pick(ctx, /grid/i);
  const others = rest(ctx, grid);
  const rows: [string, string, string, ReviewValue[]][] = [
    ["Natural gas", "53.06 kg CO₂/MMBtu", "EPA Emission Factors Hub 2025, Table 1", []],
    ["Propane", "62.87 kg CO₂/MMBtu", "EPA Emission Factors Hub 2025, Table 1", []],
    ["Diesel (mobile)", "10.21 kg CO₂/gal", "EPA Emission Factors Hub 2025, Table 2", []],
    ["Grid electricity · WECC", "", "eGRID2023, NWPP subregion", grid],
    ["Grid electricity · CAMX", "0.197 kgCO₂e/kWh", "eGRID2023, CAMX subregion", []],
    ["R-404A", "GWP 3,922", "IPCC AR5", []],
  ];
  return (
    <Page n={1} of={1}>
      <h3 className="s1-dd-title">Emission factors used · FY2025</h3>
      <div className="s1-dd-table s1-dd-table--3">
        <span>Source</span>
        <span>Factor</span>
        <span>Reference</span>
        {rows.map(([source, factor, reference, vs]) => (
          <FactorRow key={source} ctx={ctx} source={source} factor={factor} reference={reference} vs={vs} />
        ))}
      </div>
      {others.map((v) => (
        <Row key={v.id} label={v.whatItIs}>
          <Hl ctx={ctx} vs={[v]} />
        </Row>
      ))}
    </Page>
  );
}

function FactorRow({ ctx, source, factor, reference, vs }: { ctx: Ctx; source: string; factor: string; reference: string; vs: ReviewValue[] }) {
  return (
    <>
      <span>{source}</span>
      <span>{vs.length ? <Hl ctx={ctx} vs={vs} /> : factor}</span>
      <span className="s1-dd-dim">{reference}</span>
    </>
  );
}

/* ============================ generic statement ============================ */

function Statement({ ctx }: { ctx: Ctx }) {
  const first = ctx.values[0];
  return (
    <Page n={1} of={1}>
      <h3 className="s1-dd-title">{first.documentType}</h3>
      <div className="s1-dd-dim">{first.filename} · {first.period}</div>
      <h4 className="s1-dd-h">Figures on this document</h4>
      {ctx.values.map((v) => (
        <Row key={v.id} label={v.whatItIs}>
          <Hl ctx={ctx} vs={[v]} />
        </Row>
      ))}
    </Page>
  );
}
