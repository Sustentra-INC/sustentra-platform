import type { CatalogField, MethodologyValue } from "../api/methodologyReview";

export function valueText(value: MethodologyValue | undefined): string {
  if (value === null || value === undefined || value === "") return "";
  if (Array.isArray(value)) {
    // A list of entries ({source_type, method}) reads "Source: method"; a list of names reads as a comma list.
    if (value.some((v) => v !== null && typeof v === "object")) {
      return value
        .map((v) =>
          v !== null && typeof v === "object" && !Array.isArray(v) && typeof v.source_type === "string"
            ? `${v.source_type}: ${valueText(v.method as MethodologyValue)}`
            : v !== null && typeof v === "object" && !Array.isArray(v) && typeof v.option === "string"
              ? `${v.option}${v.wording ? ` (${valueText(v.wording as MethodologyValue)})` : ""}`
              : valueText(v as MethodologyValue)
        )
        .join("; ");
    }
    return value.join(", ");
  }
  if (
    typeof value === "object" &&
    typeof value.start === "string" &&
    typeof value.end === "string" &&
    Object.keys(value).every((k) => ["start", "end", "start_implied", "end_implied", "implied_from", "basis"].includes(k))
  ) {
    // A date range: a date the report does not print reads "implied" (with how it was worked out when the year came
    // from the title); the derived basis follows ("calendar year").
    const how = typeof value.implied_from === "string" && value.implied_from ? ` (${value.implied_from})` : "";
    const flag = (implied: unknown) => (implied === true ? ` implied${how}` : "");
    const basis = typeof value.basis === "string" && value.basis ? `, ${value.basis.toLowerCase()}` : "";
    return `${value.start}${flag(value.start_implied)} to ${value.end}${flag(value.end_implied)}${basis}`;
  }
  if (typeof value === "object" && typeof value.name === "string" && ("included" in value || "operational_control" in value)) {
    // An entity: each percentage is optional, so each is labelled (a bare "51" would not say which one it is).
    const pct = (v: MethodologyValue | undefined, label: string) => (typeof v === "number" ? [`${label} ${v}%`] : []);
    const facilities = Array.isArray(value.facilities) && value.facilities.length ? [`facilities: ${value.facilities.join(", ")}`] : [];
    return [value.name, ...facilities, ...pct(value.equity_share_pct, "equity share"), ...pct(value.financial_control, "financial control"), ...(value.included ? [`included: ${valueText(value.included)}`] : []), ...(value.control_quoted || value.operational_control ? [`operational control (as quoted): ${valueText((value.control_quoted ?? value.operational_control) as MethodologyValue)}`] : [])]
      .filter(Boolean)
      .join(" · ");
  }
  if (typeof value === "object") {
    return Object.entries(value)
      .map(([, v]) => valueText(v))
      .filter(Boolean)
      .join(" · ");
  }
  return String(value);
}


/** Plain words for why a suggestion batch was dropped; an unknown code shows as its own words. */
const DROP_REASON: Record<string, string> = {
  empty_value: "No value given",
  unknown_line: "Cited a line that isn't in the document",
  quote_not_on_document: "Quote not found in the document, or shorter than 8 characters",
  ambiguous_quote: "Quote appears in more than one place",
  value_not_in_quote: "Value isn't in the quoted text",
  unknown_document: "Cited a document that wasn't read",
  invalid_value: "Value isn't one of the allowed options",
  unknown_field: "Not a methodology field",
  not_an_inclusion: "Said an entity is left out, or gave no sign it is in the boundary",
  not_a_boundary_sentence: "Not a sentence about what the boundary covers",
};

export function dropReasonWords(code: string): string {
  return DROP_REASON[code] ?? code.replaceAll("_", " ");
}


/** Subscript digits in a gas's chemical name: CO2 reads CO₂. */
export function chemical(text: string): string {
  const sub: Record<string, string> = { "2": "₂", "3": "₃", "4": "₄", "6": "₆" };
  return text.replace(/\b(CO2|CH4|N2O|SF6|NF3)\b/g, (g) => g.replace(/\d/g, (d) => sub[d] ?? d));
}


/** The row's name as the table shows it: sentence case, a gas without its "Gas:" prefix and with subscripts. */
export function itemLabel(def: CatalogField): string {
  const bare = def.group === "gases" ? def.label.replace(/^Gas:\s*/i, "") : def.group === "scope1" ? def.label.replace(/^Scope 1\s+/i, "") : def.label;
  return chemical(bare);
}

