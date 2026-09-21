"use client";

/**
 * The prepared demo document, rendered as an inline SVG (offline, crisp,
 * scalable). A realistic commercial electricity invoice for Cascade Provisions
 * (Kent Cannery, Feb 2025), built to carry the figures a compliance analyst
 * actually verifies: billing period, delivered consumption, peak demand, the
 * location-based emission factor, and the derived emissions.
 *
 * Every verifiable figure has a named mark in INVOICE_MARKS (normalized
 * {x,y,w,h}). All marks render as faint highlights so the reviewer sees at a
 * glance what was read; the currently selected value (`highlight`) draws bright
 * on top and lands exactly on its figure.
 */

const W = 850;
const H = 1150;

type Box = { x: number; y: number; w: number; h: number };

/** Normalized highlight boxes, authored to sit on each figure below. */
export const INVOICE_MARKS: Record<string, Box> = {
  period: { x: 0.729, y: 0.1357, w: 0.235, h: 0.0261 },
  consumption: { x: 0.776, y: 0.4104, w: 0.182, h: 0.0261 },
  demand: { x: 0.8235, y: 0.44, w: 0.135, h: 0.0261 },
  emissionFactor: { x: 0.72, y: 0.565, w: 0.241, h: 0.0261 },
  emissions: { x: 0.7906, y: 0.621, w: 0.1706, h: 0.0261 },
};

/** Back-compat: the primary consumption figure. */
export const INVOICE_HIGHLIGHT = INVOICE_MARKS.consumption;

const ALL_MARKS = Object.values(INVOICE_MARKS);

function sameBox(a: Box, b: Box): boolean {
  return Math.abs(a.x - b.x) < 0.001 && Math.abs(a.y - b.y) < 0.001;
}

export function InvoicePage({ highlight }: { highlight?: Box | null }) {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="s1-invoice" role="img" aria-label="Electricity invoice">
      <rect x="0" y="0" width={W} height={H} fill="#ffffff" />

      {/* header */}
      <rect x="0" y="0" width={W} height="96" fill="#1f3a5f" />
      <text x="48" y="56" fill="#ffffff" fontFamily="Georgia, 'Times New Roman', serif" fontSize="28" fontWeight="700">
        Pacific Grid Electric
      </text>
      <text x="48" y="78" fill="#c9d6e6" fontSize="12.5">Commercial energy statement</text>
      <text x={W - 48} y="44" fill="#ffffff" fontSize="12.5" textAnchor="end">Invoice PGE-2025-03-44712</text>
      <text x={W - 48} y="64" fill="#c9d6e6" fontSize="11.5" textAnchor="end">Statement date: 08 Mar 2025</text>

      {/* service account + service period */}
      <text x="48" y="146" fill="#6a6a6a" fontSize="11" letterSpacing="1">SERVICE ACCOUNT</text>
      <text x="48" y="172" fill="#1a1a1a" fontSize="15" fontWeight="700">Cascade Provisions Co.</text>
      <text x="48" y="192" fill="#333" fontSize="12.5">Kent Cannery · 1400 Marine View Dr, Kent, WA</text>
      <text x="48" y="212" fill="#333" fontSize="12.5">Account 4471-302 · Rate schedule E-19</text>

      <text x={W - 48} y="146" fill="#6a6a6a" fontSize="11" letterSpacing="1" textAnchor="end">SERVICE PERIOD</text>
      <text x={W - 48} y="178" fill="#111" fontSize="15" fontWeight="700" textAnchor="end">01 Feb – 28 Feb 2025</text>
      <text x={W - 48} y="200" fill="#333" fontSize="12.5" textAnchor="end">Billing days: 28</text>

      <line x1="48" y1="240" x2={W - 48} y2="240" stroke="#e0e0e0" strokeWidth="1" />

      {/* meter readings */}
      <text x="48" y="284" fill="#6a6a6a" fontSize="11" letterSpacing="1">METER READINGS · METER 88-2231</text>
      <Row y={318} label="Previous read (01 Feb)" value="1,284,500 kWh" />
      <Row y={350} label="Current read (28 Feb)" value="1,466,900 kWh" />
      <Row y={382} label="Register multiplier" value="1.0" />

      <line x1="48" y1="414" x2={W - 48} y2="414" stroke="#e0e0e0" strokeWidth="1" />

      {/* usage this period */}
      <text x="48" y="454" fill="#6a6a6a" fontSize="11" letterSpacing="1">USAGE THIS PERIOD</text>
      <text x="48" y="494" fill="#1a1a1a" fontSize="15">Electricity delivered</text>
      <text x={W - 48} y="494" fill="#111" fontSize="19" fontWeight="700" textAnchor="end">182,400 kWh</text>
      <text x="48" y="528" fill="#1a1a1a" fontSize="15">Peak demand</text>
      <text x={W - 48} y="528" fill="#111" fontSize="16" textAnchor="end">1,240 kW</text>
      <text x="48" y="562" fill="#1a1a1a" fontSize="15">Power factor</text>
      <text x={W - 48} y="562" fill="#111" fontSize="15" textAnchor="end">0.98</text>

      <line x1="48" y1="596" x2={W - 48} y2="596" stroke="#e0e0e0" strokeWidth="1" />

      {/* emissions basis — what a compliance analyst checks */}
      <text x="48" y="636" fill="#6a6a6a" fontSize="11" letterSpacing="1">EMISSIONS BASIS (LOCATION-BASED)</text>
      <text x="48" y="672" fill="#1a1a1a" fontSize="15">Emission factor · eGRID WECC subregion</text>
      <text x={W - 48} y="672" fill="#111" fontSize="16" fontWeight="700" textAnchor="end">0.223 kgCO2e/kWh</text>
      <text x="48" y="704" fill="#1a1a1a" fontSize="15">Grid subregion</text>
      <text x={W - 48} y="704" fill="#111" fontSize="15" textAnchor="end">NWPP · eGRID 2024</text>
      <text x="48" y="736" fill="#1a1a1a" fontSize="15">Estimated location-based emissions</text>
      <text x={W - 48} y="736" fill="#111" fontSize="16" fontWeight="700" textAnchor="end">40.68 tCO2e</text>

      <line x1="48" y1="768" x2={W - 48} y2="768" stroke="#e0e0e0" strokeWidth="1" />

      {/* charges */}
      <text x="48" y="808" fill="#6a6a6a" fontSize="11" letterSpacing="1">CHARGES</text>
      <Row y={840} label="Energy charge (182,400 kWh × $0.211)" value="$38,486.40" small />
      <Row y={870} label="Demand charge (1,240 kW × $6.20)" value="$7,688.00" small />
      <Row y={900} label="Fixed service charge" value="$1,845.75" small />
      <Row y={930} label="State utility tax" value="$199.99" small />

      <line x1="48" y1="964" x2={W - 48} y2="964" stroke="#1f3a5f" strokeWidth="2" />
      <text x="48" y="1000" fill="#1a1a1a" fontSize="17" fontWeight="700">Total amount due</text>
      <text x={W - 48} y="1000" fill="#1f3a5f" fontSize="21" fontWeight="700" textAnchor="end">$48,220.15</text>
      <text x="48" y="1026" fill="#555" fontSize="12.5">Payment due by 29 Mar 2025</text>

      {/* footer */}
      <line x1="48" y1="1088" x2={W - 48} y2="1088" stroke="#e0e0e0" strokeWidth="1" />
      <text x="48" y="1114" fill="#8a8a8a" fontSize="10.5">
        Pacific Grid Electric · PO Box 4471, Seattle WA · billing@pacificgrid.example
      </text>
      <text x="48" y="1132" fill="#8a8a8a" fontSize="10.5">
        Factors from eGRID 2024; emissions shown are location-based per GHG Protocol Scope 2 guidance.
      </text>

      {/* faint marks on every verifiable figure */}
      {ALL_MARKS.map((m, i) =>
        highlight && sameBox(m, highlight) ? null : (
          <rect
            key={i}
            x={m.x * W}
            y={m.y * H}
            width={m.w * W}
            height={m.h * H}
            className="s1-invoice__hl s1-invoice__hl--faint"
          />
        )
      )}

      {/* bright active highlight */}
      {highlight ? (
        <rect
          x={highlight.x * W}
          y={highlight.y * H}
          width={highlight.w * W}
          height={highlight.h * H}
          className="s1-invoice__hl"
        />
      ) : null}
    </svg>
  );
}

function Row({ y, label, value, small = false }: { y: number; label: string; value: string; small?: boolean }) {
  return (
    <>
      <text x="48" y={y} fill="#333" fontSize={small ? 13 : 14}>
        {label}
      </text>
      <text x={W - 48} y={y} fill="#111" fontSize={small ? 13 : 14} textAnchor="end" fontFamily="'SF Mono', Menlo, monospace">
        {value}
      </text>
    </>
  );
}
