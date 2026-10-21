"use client";

import { Highlighter, X } from "lucide-react";
import { createContext, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";

import type { EngagementConfig } from "../../types";
import type { ReviewValue, ScopePlacement } from "../../types/review";

/** A figure the reviewer highlighted on the page, to add (or fill in) as a value. */
export interface HighlightEntry {
  /** Where on the drawn document: the figure's anchor. */
  docAnchor: string;
  whatItIs: string;
  value: string;
  unit: string;
  scope: ScopePlacement;
  page: number;
}

/**
 * A demo document drawn whole, as the client sent it: every page, every line, with each
 * value the reading took from it highlighted in place. Values the reading could not find
 * are marked where they belong. Clicking a highlight selects its value (the review cards
 * scroll to it); selecting a card scrolls the document to its highlight.
 *
 * With ``onAddValue``, the reviewer can highlight a figure the reading missed: every
 * other figure on the page becomes a target, and the one clicked is added as a value
 * (or fills in a value the reading could not find), kept as a correction to the reading.
 * In review, the legend and the highlight switch live in the values pane, pinned where
 * the reviewer works (``highlighting``); on its own, the document draws its own legend.
 */
export function DemoDocument({
  values,
  engagement,
  selectedId,
  onPick,
  onAddValue,
  highlighting,
  onHighlightingChange,
}: {
  /** Every value read from this one document. */
  values: ReviewValue[];
  engagement: EngagementConfig;
  selectedId: string | null;
  /** The values behind a clicked highlight (several when one figure feeds two values). */
  onPick: (ids: string[]) => void;
  /** Lets the reviewer highlight a figure the reading missed. */
  onAddValue?: (entry: HighlightEntry) => void;
  /** Highlight mode, switched from outside (the values pane); the document then has no legend. */
  highlighting?: boolean;
  onHighlightingChange?: (on: boolean) => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const [own, setOwn] = useState(false);
  const controlled = Boolean(onHighlightingChange);
  const picking = controlled ? Boolean(highlighting) : own;
  const setPicking = (on: boolean) => (onHighlightingChange ? onHighlightingChange(on) : setOwn(on));
  const [target, setTarget] = useState<FigureTarget | null>(null);

  useEffect(() => {
    if (!picking) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (target) setTarget(null);
      else if (onHighlightingChange) onHighlightingChange(false);
      else setOwn(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [picking, target, onHighlightingChange]);

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
  const ctx: Ctx = {
    values,
    engagement,
    selectedId,
    onPick,
    picking: picking && Boolean(onAddValue),
    onFigure: (fig, el) => {
      const box = el.getBoundingClientRect();
      const frame = el.closest(".s1-dd")?.getBoundingClientRect();
      if (!frame) return;
      setTarget({ ...fig, top: box.bottom - frame.top + 6, left: Math.max(0, Math.min(box.left - frame.left, frame.width - 300)) });
    },
  };
  const missing = values.filter(isMissing).length;

  return (
    <div className={`s1-dd${ctx.picking ? " is-picking" : ""}`} ref={root}>
      {controlled ? null : (
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
        {onAddValue ? (
          <button
            className={`s1-dd-pick${picking ? " is-on" : ""}`}
            type="button"
            aria-pressed={picking}
            onClick={() => {
              setPicking(!picking);
              setTarget(null);
            }}
          >
            <Highlighter aria-hidden /> {picking ? "Done highlighting" : "Highlight a figure"}
          </button>
        ) : null}
      </div>
      )}
      {ctx.picking && !target ? (
        <div className="s1-dd-pickhint" role="status">
          Click any figure the reading missed to add it as a value. Press Esc when you are done.
        </div>
      ) : null}
      {target && onAddValue ? (
        <HighlightForm
          target={target}
          values={values}
          onCancel={() => setTarget(null)}
          onAdd={(entry) => {
            onAddValue(entry);
            setTarget(null);
            setPicking(false);
          }}
        />
      ) : null}
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
  /** Highlight mode: plain figures are targets. */
  picking: boolean;
  onFigure: (fig: { docAnchor: string; label: string; text: string; page: number }, el: HTMLElement) => void;
}

interface FigureTarget {
  docAnchor: string;
  label: string;
  text: string;
  page: number;
  top: number;
  left: number;
}

const PageNumber = createContext(1);

/** A figure the reading did not take. Highlighted once a reviewer adds it; in highlight
 *  mode, a target that adds it. */
function Fig({ ctx, anchor, label, children }: { ctx: Ctx; anchor: string; label: string; children: ReactNode }) {
  const page = useContext(PageNumber);
  const keyed = ctx.values.filter((v) => v.docAnchor === anchor);
  if (keyed.length) return <Hl ctx={ctx} vs={keyed}>{children}</Hl>;
  if (!ctx.picking) return <>{children}</>;
  return (
    <button
      type="button"
      className="s1-dd-fig"
      data-anchor={anchor}
      title={`Add ${label} as a value`}
      onClick={(e) => ctx.onFigure({ docAnchor: anchor, label, text: e.currentTarget.textContent ?? "", page }, e.currentTarget)}
    >
      {children}
    </button>
  );
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
    <PageNumber.Provider value={n}>
      <section className={`s1-dd-page${tone ? ` s1-dd-page--${tone}` : ""}`} aria-label={`Page ${n} of ${of}`}>
        {children}
        <footer className="s1-dd-foot">Page {n} of {of}</footer>
      </section>
    </PageNumber.Provider>
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
              {periodEnd.length ? <Hl ctx={ctx} vs={periodEnd}>{isMissing(periodEnd[0]) ? "not printed" : periodEnd[0].value}</Hl> : <Fig ctx={ctx} anchor="service-period-end" label="Service period end date">{period.end}</Fig>}
            </div>
            <div className="s1-dd-dim">Billing days <Fig ctx={ctx} anchor="billing-days" label="Billing days">{period.days}</Fig></div>
          </div>
        </div>

        <h4 className="s1-dd-h">Meter readings · Meter {kind === "electricity" ? "E" : "G"}{String(s % 9000).padStart(4, "0")}</h4>
        <Row label={<>Previous read (<Fig ctx={ctx} anchor="previous-read-date" label="Service period start date">{period.start}</Fig>)</>}>
          <Fig ctx={ctx} anchor="previous-read" label="Previous meter read">{fmt(previous)} {kind === "electricity" ? "kWh" : "ccf"}</Fig>
        </Row>
        <Row label={<>Current read (<Fig ctx={ctx} anchor="current-read-date" label="Service period end date">{period.end}</Fig>)</>}>
          <Fig ctx={ctx} anchor="current-read" label="Current meter read">
            {fmt(previous + (kind === "electricity" ? qty : qty * 0.97))} {kind === "electricity" ? "kWh" : "ccf"}
          </Fig>
        </Row>
        <Row label="Multiplier"><Fig ctx={ctx} anchor="multiplier" label="Meter multiplier">1.000</Fig></Row>

        <h4 className="s1-dd-h">Usage this period</h4>
        <Row label={kind === "electricity" ? "Electricity delivered" : "Natural gas used"} strong>
          {consumption.length ? <Hl ctx={ctx} vs={consumption} /> : <Fig ctx={ctx} anchor="consumption" label={kind === "electricity" ? "Electricity consumed" : "Natural gas consumed"}>{`${fmt(qty)} ${unit}`}</Fig>}
        </Row>
        {kind === "electricity" ? (
          <>
            <Row label="Peak demand">{peak.length ? <Hl ctx={ctx} vs={peak} /> : <Fig ctx={ctx} anchor="peak-demand" label="Peak demand">{`${fmt(demandKw)} kW`}</Fig>}</Row>
            <Row label="Power factor"><Fig ctx={ctx} anchor="power-factor" label="Power factor">0.96</Fig></Row>
          </>
        ) : (
          <>
            <Row label="Therm factor"><Fig ctx={ctx} anchor="therm-factor" label="Therm factor">1.037</Fig></Row>
            <Row label="Heat content"><Fig ctx={ctx} anchor="heat-content" label="Heat content">{fmt(qty / 10, 1)} MMBtu</Fig></Row>
          </>
        )}
        {others.map((v) => (
          <Row key={v.id} label={v.whatItIs}>
            <Hl ctx={ctx} vs={[v]} />
          </Row>
        ))}

        <h4 className="s1-dd-h">Charges</h4>
        <Row label={`${kind === "electricity" ? "Energy" : "Gas supply"} (${fmt(qty)} ${unit} × $${rate.toFixed(3)})`}>
          <Fig ctx={ctx} anchor="energy-charge" label={kind === "electricity" ? "Energy charge" : "Gas supply charge"}>{`$${fmt(energy, 2)}`}</Fig>
        </Row>
        {kind === "electricity" ? (
          <Row label={`Demand (${fmt(demandKw)} kW × $6.25)`}>
            <Fig ctx={ctx} anchor="demand-charge" label="Demand charge">{`$${fmt(demandCharge, 2)}`}</Fig>
          </Row>
        ) : null}
        <Row label="Basic service charge"><Fig ctx={ctx} anchor="basic-charge" label="Basic service charge">{`$${fmt(fixed, 2)}`}</Fig></Row>
        <Row label="State and local taxes"><Fig ctx={ctx} anchor="taxes" label="Taxes">{`$${fmt(tax, 2)}`}</Fig></Row>
        <Row label="Amount due" strong>
          <Fig ctx={ctx} anchor="amount-due" label="Amount due">{`$${fmt(total, 2)}`}</Fig>
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
        <span>{added.length ? <Hl ctx={ctx} vs={added} /> : <Fig ctx={ctx} anchor="rtu3-added" label="R-404A added on service">0 kg</Fig>}</span>
        <span>
          {recovered.length ? (
            <Hl ctx={ctx} vs={recovered}>
              {recovered[0].value === "n/a" ? <span className="s1-dd-smudge">illegible</span> : undefined}
            </Hl>
          ) : (
            <Fig ctx={ctx} anchor="rtu3-recovered" label="R-404A recovered on service">0 kg</Fig>
          )}
        </span>
        <span>WIC-1 · walk-in cooler</span>
        <span>R-404A</span>
        <span><Fig ctx={ctx} anchor="wic1-added" label="R-404A added on service (WIC-1)">0 kg</Fig></span>
        <span><Fig ctx={ctx} anchor="wic1-recovered" label="R-404A recovered on service (WIC-1)">0 kg</Fig></span>
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
                      {vs.length ? (
                        <Hl ctx={ctx} vs={vs}>{vs[0].value}</Hl>
                      ) : row[ci] && r > 0 ? (
                        <Fig ctx={ctx} anchor={`${c}${r + 1}`} label={layout.rows[r][0] || `Cell ${c}${r + 1}`}>{row[ci]}</Fig>
                      ) : (
                        row[ci]
                      )}
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
    ["R-404A", "GWP 3,943", "IPCC AR5", []],
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
      <span>{vs.length ? <Hl ctx={ctx} vs={vs} /> : <Fig ctx={ctx} anchor={`factor-${source}`} label={`Emission factor · ${source}`}>{factor}</Fig>}</span>
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

/* ============================ highlight a figure ============================ */

const SCOPES: { value: ScopePlacement; label: string }[] = [
  { value: "scope1", label: "Scope 1" },
  { value: "scope2_location", label: "Scope 2 · location-based" },
  { value: "scope2_market", label: "Scope 2 · market-based" },
  { value: "not_placed", label: "Not placed in a scope" },
];

const MONTH_WORD = /\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b/i;

/** "41,200 kWh" -> 41,200 + kWh; "$45,920.00" -> 45,920.00 + USD; a date stays whole. */
export function parseFigure(text: string): { value: string; unit: string } {
  const t = text.replace(/\s+/g, " ").trim();
  if (MONTH_WORD.test(t)) return { value: t, unit: "" };
  const money = /^\$\s*([\d,]+(?:\.\d+)?)$/.exec(t);
  if (money) return { value: money[1], unit: "USD" };
  const figure = /^([\d,]+(?:\.\d+)?)\s*(.*)$/.exec(t);
  return figure ? { value: figure[1], unit: figure[2] } : { value: t, unit: "" };
}

function defaultScope(documentType: string, label: string): ScopePlacement {
  if (!/consumed|delivered|used|added on service|recovered/i.test(label)) return "not_placed";
  if (documentType === "Electricity bill") return "scope2_location";
  return /gas|fuel|refrigerant/i.test(documentType) ? "scope1" : "not_placed";
}

function HighlightForm({
  target,
  values,
  onCancel,
  onAdd,
}: {
  target: FigureTarget;
  values: ReviewValue[];
  onCancel: () => void;
  onAdd: (entry: HighlightEntry) => void;
}) {
  const listId = useId();
  const parsed = parseFigure(target.text);
  const missingNames = values.filter(isMissing).map((v) => v.whatItIs);
  const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase();
  const [whatItIs, setWhatItIs] = useState(missingNames.find((n) => same(n, target.label)) ?? target.label);
  const [value, setValue] = useState(parsed.value);
  const [unit, setUnit] = useState(parsed.unit);
  const [scope, setScope] = useState<ScopePlacement>(defaultScope(values[0].documentType, target.label));
  const fills = missingNames.some((n) => same(n, whatItIs));
  const suggestions = [...new Set([...missingNames, target.label, ...values.map((v) => v.whatItIs)])];
  return (
    <form
      className="s1-dd-hlform"
      style={{ top: target.top, left: target.left }}
      onSubmit={(e) => {
        e.preventDefault();
        if (!whatItIs.trim() || !value.trim()) return;
        onAdd({ docAnchor: target.docAnchor, whatItIs: whatItIs.trim(), value: value.trim(), unit: unit.trim(), scope, page: target.page });
      }}
    >
      <div className="s1-dd-hlform__head">
        <strong>{fills ? "Fill in a value the reading missed" : "Add this figure as a value"}</strong>
        <button type="button" className="s1-dd-hlform__x" aria-label="Cancel" onClick={onCancel}>
          <X aria-hidden />
        </button>
      </div>
      <div className="s1-dd-hlform__quote">
        “{target.text.trim()}” · page {target.page}
      </div>
      <label>
        <span>What it is</span>
        <input list={listId} value={whatItIs} autoFocus onChange={(e) => setWhatItIs(e.target.value)} />
        <datalist id={listId}>
          {suggestions.map((s) => (
            <option key={s} value={s} />
          ))}
        </datalist>
      </label>
      <div className="s1-dd-hlform__pair">
        <label>
          <span>Value</span>
          <input value={value} onChange={(e) => setValue(e.target.value)} />
        </label>
        <label>
          <span>Unit</span>
          <input value={unit} onChange={(e) => setUnit(e.target.value)} />
        </label>
      </div>
      <label>
        <span>Scope</span>
        <select value={scope} onChange={(e) => setScope(e.target.value as ScopePlacement)}>
          {SCOPES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
      <div className="s1-dd-hlform__actions">
        <button className="s1-button s1-button--pri s1-button--compact" type="submit" disabled={!whatItIs.trim() || !value.trim()}>
          {fills ? "Fill in" : "Add value"}
        </button>
        <span>Kept as a correction to the reading</span>
      </div>
    </form>
  );
}
