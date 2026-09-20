"use client";

/**
 * The prepared demo document, rendered as an inline SVG (offline, crisp,
 * scalable · no external image, no network). It is a realistic electricity
 * invoice for Cascade Provisions. `highlight` is a normalized {x,y,w,h} box
 * (0..1 of the page) drawn over the value; the coordinates are authored to land
 * exactly on the consumption figure.
 */

const W = 850;
const H = 1100;

export function InvoicePage({ highlight }: { highlight?: { x: number; y: number; w: number; h: number } | null }) {
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="s1-invoice" role="img" aria-label="Electricity invoice">
      <rect x="0" y="0" width={W} height={H} fill="#ffffff" />
      {/* header */}
      <rect x="0" y="0" width={W} height="96" fill="#1f3a5f" />
      <text x="48" y="58" fill="#ffffff" fontFamily="Georgia, serif" fontSize="30" fontWeight="700">
        Pacific Grid Electric
      </text>
      <text x="48" y="80" fill="#c9d6e6" fontSize="13">
        Commercial energy statement
      </text>
      <text x={W - 48} y="46" fill="#ffffff" fontSize="13" textAnchor="end">
        Invoice PGE-2025-03-44712
      </text>
      <text x={W - 48} y="66" fill="#c9d6e6" fontSize="12" textAnchor="end">
        Statement date: 08 Mar 2025
      </text>

      {/* bill-to + account */}
      <text x="48" y="150" fill="#555" fontSize="12" letterSpacing="1">SERVICE ACCOUNT</text>
      <text x="48" y="176" fill="#1a1a1a" fontSize="16" fontWeight="700">Cascade Provisions Co.</text>
      <text x="48" y="198" fill="#333" fontSize="13">Kent Cannery · 1400 Marine View Dr, Kent, WA</text>
      <text x="48" y="218" fill="#333" fontSize="13">Account 4471-302 · Rate schedule E-19</text>

      <text x={W - 48} y="150" fill="#555" fontSize="12" letterSpacing="1" textAnchor="end">SERVICE PERIOD</text>
      <text x={W - 48} y="176" fill="#1a1a1a" fontSize="15" textAnchor="end">01 Feb – 28 Feb 2025</text>
      <text x={W - 48} y="198" fill="#333" fontSize="13" textAnchor="end">Billing days: 28</text>

      <line x1="48" y1="248" x2={W - 48} y2="248" stroke="#e0e0e0" strokeWidth="1" />

      {/* meter reads */}
      <text x="48" y="288" fill="#555" fontSize="12" letterSpacing="1">METER READINGS · METER 88-2231</text>
      <MeterRow y={320} label="Previous read (01 Feb)" value="1,284,500 kWh" />
      <MeterRow y={352} label="Current read (28 Feb)" value="1,466,900 kWh" />
      <MeterRow y={384} label="Multiplier" value="1.0" />

      <line x1="48" y1="418" x2={W - 48} y2="418" stroke="#e0e0e0" strokeWidth="1" />

      {/* usage summary · the highlight target */}
      <text x="48" y="458" fill="#555" fontSize="12" letterSpacing="1">USAGE THIS PERIOD</text>
      <text x="48" y="490" fill="#1a1a1a" fontSize="16">Electricity delivered</text>
      <text x={W - 48} y="490" fill="#111" fontSize="20" fontWeight="700" textAnchor="end">
        182,400 kWh
      </text>
      <text x="48" y="520" fill="#1a1a1a" fontSize="16">Peak demand</text>
      <text x={W - 48} y="520" fill="#111" fontSize="16" textAnchor="end">1,240 kW</text>
      <text x="48" y="548" fill="#1a1a1a" fontSize="16">Power factor</text>
      <text x={W - 48} y="548" fill="#111" fontSize="16" textAnchor="end">0.98</text>

      <line x1="48" y1="582" x2={W - 48} y2="582" stroke="#e0e0e0" strokeWidth="1" />

      {/* charges */}
      <text x="48" y="622" fill="#555" fontSize="12" letterSpacing="1">CHARGES</text>
      <ChargeRow y={654} label="Energy charge (182,400 kWh × $0.211)" value="$38,486.40" />
      <ChargeRow y={684} label="Demand charge (1,240 kW × $6.20)" value="$7,688.00" />
      <ChargeRow y={714} label="Fixed service charge" value="$1,845.75" />
      <ChargeRow y={744} label="State utility tax" value="$199.99" />

      <line x1="48" y1="778" x2={W - 48} y2="778" stroke="#1f3a5f" strokeWidth="2" />
      <text x="48" y="812" fill="#1a1a1a" fontSize="18" fontWeight="700">Total amount due</text>
      <text x={W - 48} y="812" fill="#1f3a5f" fontSize="22" fontWeight="700" textAnchor="end">$48,220.15</text>
      <text x="48" y="838" fill="#555" fontSize="13">Payment due by 29 Mar 2025</text>

      {/* footer */}
      <line x1="48" y1="1010" x2={W - 48} y2="1010" stroke="#e0e0e0" strokeWidth="1" />
      <text x="48" y="1040" fill="#888" fontSize="11">
        Pacific Grid Electric · PO Box 4471, Seattle WA · billing@pacificgrid.example
      </text>
      <text x="48" y="1058" fill="#888" fontSize="11">
        Emission factor (location-based): 0.223 kgCO2e/kWh · eGRID WECC subregion
      </text>

      {/* highlight overlay */}
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

function MeterRow({ y, label, value }: { y: number; label: string; value: string }) {
  return (
    <>
      <text x="48" y={y} fill="#333" fontSize="14">{label}</text>
      <text x={W - 48} y={y} fill="#111" fontSize="14" textAnchor="end" fontFamily="monospace">{value}</text>
    </>
  );
}

function ChargeRow({ y, label, value }: { y: number; label: string; value: string }) {
  return (
    <>
      <text x="48" y={y} fill="#333" fontSize="14">{label}</text>
      <text x={W - 48} y={y} fill="#111" fontSize="14" textAnchor="end" fontFamily="monospace">{value}</text>
    </>
  );
}

/** Normalized highlight over "182,400 kWh" on the usage line. */
export const INVOICE_HIGHLIGHT = { x: 0.64, y: 0.428, w: 0.18, h: 0.026 };
