# Sustentra Intake Profile → Methodology Schema Mapping — v0.2

**Status:** Revised after ISO 14064 alignment audit (all 6 FAILs + 1 suggestion applied, founder-reviewed and accepted). Target location once committed: `intake/profile_schema_mapping.md` on branch `feature/intake-profile-schema`.
**Sources used:** `reference-data/methodology/S2_General_Methodology_Schema_v.1.xlsx` (1_Schema), `S2_Scope1_Data_Schema_v.1.xlsx` (1_Schema), `S2_Scope2_Data_Schema_v.1.xlsx` (S2_Schema), `reference-data/config/libraries/evidence_type_library.json` (J2 types), `legacy-schemas/copied_from_streamlit_demo/audit_setup.schema.json`; ISO 14064-1:2018 requirements (categories, uncertainty §8.3, significance criteria, report content), GHG Protocol Corporate Standard, GHG Protocol Scope 2 Guidance, EPA GHG guidance (Dec. 2023, as cited inside the Scope 1 workbook). Field IDs were read directly from the repo files.
**Principle:** The intake defines NO new emissions data points. Every answer either (a) populates an existing methodology field, (b) switches a schema block on/off, or (c) triggers an evidence request from the J2 library. Intake-only fields (state, escalation, content) are listed in §8.

## Standards basis *(added in v0.2 — audit FAIL 1)*

This mapping is built on the GHG Protocol Corporate Standard structure (Scope 1 / Scope 2) with EPA calculation methods, matching the methodology workbooks in the repo. For clients reporting under **ISO 14064-1:2018** — which replaced scope terminology with six categories — the correspondence is: **Scope 1 ↔ Category 1 (direct GHG emissions and removals)**; **Scope 2 ↔ Category 2 (indirect emissions from imported energy)**. Categories 3–6 (transport, products used, product use, other indirect) are outside product scope but their exclusion is documented per §2.7 below. Reports can therefore be issued under either framework from the same profile. Consolidation approaches named in §2.1 satisfy both frameworks; ISO 14064-1 additionally permits other consolidation methods if the organization documents and justifies them.

**Escalation classes:** `AUTO` = safe to parse, S1 may run immediately. `HUMAN` = boundary/allocation class, requires human confirmation before dependent S1 processing. `SYSTEM` = assigned by the platform, not asked.

---

## 1. Seed form (Stage 1 — structured, no chat)

| # | Intake item | Populates | Evidence triggered | Class | Reasoning |
|---|---|---|---|---|---|
| 1.1 | Company legal name + reporting year | INV-010 (`legal_reporting_entity_id`, `reporting_year`) | — | AUTO | Anchor keys for the whole inventory; every S1/S2 record joins back to INV-010. |
| 1.2 | **Responsible party: name, role, email of the person accountable for the inventory** *(added in v0.2 — audit FAIL 6)* | Intake profile field; surfaces in report content | — | AUTO | ISO 14064-1 report content requires naming the responsible party. Doubles as the client-side escalation contact for the alert pipeline. |
| 1.3 | Sites: name, full address, status | FAC-010 (`facility_id`, `facility_name`, `location`, `country_region`, `operational_status`, `period_in_scope`) | J2-007 (facility register / boundary evidence) | AUTO | Facility register is the grain everything else attaches to. Address feeds Scope 2 grid-region matching (S2-MTR-070 / S2-EFS-070) without asking the user — grid region is derived, never asked. |
| 1.4 | Industry | Legacy `audit_setup.company_and_facility_profile.industry`; intake overlay selector (intake-only) | — | AUTO | Switches vocabulary/explainer overlay (film v1). |
| 1.5 | Site type (film overlay: soundstage complex / backlot / office / workshop) | Legacy `audit_setup.facility_type`; descriptive attribute on FAC-010 | — | AUTO | Drives which screening questions appear per site. |
| 1.6 | Reporting period start/end, fiscal basis | PER-010 (`reporting_period_start`, `reporting_period_end`, `fiscal_year_basis`) | — | AUTO | Required key for all consumption/period allocation. |
| 1.7 | Own vs lease per site | ORG-050 (`lease_type`, `operational_control_over_asset_flag`, `exclusion_justification`) — partial; completed in §2 | — | HUMAN (resolved in §2) | Seed captures the raw fact; control determination is a boundary judgment. |

## 2. Boundary block (chat, HUMAN class unless noted — human-confirmed before lock)

| # | Intake item | Populates | Evidence triggered | Class | Reasoning |
|---|---|---|---|---|---|
| 2.1 | Consolidation approach (plain-language: "which parts of the business count as yours") | ORG-010 (`consolidation_approach`), ORG-025 (`control_determination_basis`, `control_verification_route`) | J2-007 | HUMAN | Named options — operational control / financial control / equity share — exist in ORG-010 and the legacy audit_setup enum, and satisfy both GHG Protocol and ISO 14064-1. ISO additionally permits other documented, justified methods *(v0.2, suggestion 1)*. SME default proposal: operational control (single-entity SMEs converge on the same inventory under all three). Human confirms. |
| 2.2 | Operations/subsidiaries list (only if >1 legal entity) | ORG-020, ORG-030 | J2-007 | HUMAN | Skipped entirely for single-entity SMEs — the common case. |
| 2.3 | Leased/rented spaces and equipment: who controls what (film: which stages are under studio control vs production control; who holds each meter) | ORG-050, ORG-055, ORG-040 (`party_role`) | J2-007, lease agreements | HUMAN | The landlord/tenant crux. Determines whether a source is the client's Scope 1/2 or the tenant's. Never auto-parsed. |
| 2.4 | Base year | BAS-010, BAS-030 | — | AUTO with condition | SME default: first reporting year = base year, standard recalculation policy template. Escalates only if prior inventories exist (then J2-014 requested). |
| 2.5 | Mid-year acquisitions/divestitures/moves | CHG-010 | J2-007 | HUMAN | Rare for SMEs; one yes/no screening question; "yes" escalates. |
| 2.6 | GWP set + gas universe | GAS-030, GAS-010 | — | SYSTEM | Methodology decision, not a client fact. System assigns per program requirements; verifier can override. Needs Todd sign-off on defaults. |
| 2.7 | **Significance criteria + justification for excluding indirect categories 3–6 (ISO) / Scope 3 (GHG Protocol)** *(added in v0.2 — audit FAIL 3)* | EXC-010 pattern at category level + intake statement field | — | HUMAN | ISO 14064-1 requires a documented process for determining significant indirect emissions and justifying exclusions; a Scope-1&2-only inventory conforms only with this recorded. Templated default statement for SMEs, human-confirmed. |

## 3. Scope 1 screening — stationary combustion (per site)

| # | Intake item | Populates | Evidence triggered | Class | Reasoning |
|---|---|---|---|---|---|
| 3.1 | "Any equipment on site that burns fuel?" (heating boilers, gas kitchens, workshops) — yes/no + list | Registers: S1-STC-100; method claim S1-STC-140 defaulted (§7) | J2-008, then J2-001 / J2-003 per fuel type | AUTO | "Yes" activates the STC block; per-fuel records land in S1-STC-110/010 from extracted documents, not typed answers. |
| 3.2 | "Any backup or emergency generators?" (film default: expected yes for stages) | S1-STC-100 register; activity-estimation route S1-STC-220 when fuel isn't separately metered | J2-005, J2-003 | AUTO | Schema provides the emergency-generator estimation path (S1-STC-220/230, EPA §3.1 p.9). |
| 3.3 | **"Is any of your fuel biodiesel, renewable diesel, or a blend?"** *(added in v0.2 — audit FAIL 4)* | S1-STC-300 (`fuel_biogenic_fraction`, `fuel_fossil_fraction`); routes outputs via S1-STC-330/340/350 | Fuel spec sheets / delivery invoices (J2-003) | AUTO | ISO 14064-1 requires biogenic CO₂ quantified separately; the workbook's biogenic routes exist but were never activated by a screening question. Renewable diesel in generators is increasingly common at studios. Applies to mobile fuels too via S1-MOB-310. |
| 3.4 | Screening: "No" to 3.1/3.2 | **"Screened, not present" completeness record (intake-side status referencing the source category)** *(revised in v0.2 — audit FAIL 5)* | — | AUTO | Non-existence is a completeness statement, not an exclusion. EXC-010 (`exclusion_rationale`, `exclusion_materiality_basis`) is reserved for sources that exist but are excluded with justification. Applies to all §3–§5 "no" answers. |

## 4. Scope 1 screening — mobile (per entity)

| # | Intake item | Populates | Evidence triggered | Class | Reasoning |
|---|---|---|---|---|---|
| 4.1 | "Vehicles or motorized equipment the company owns/leases?" (film: carts, forklifts, shuttles, trucks) + fleet list | S1-MOB-400, S1-MOB-100 | J2-008; then J2-004 or J2-003 | AUTO with flag | J2-004's own default rule is `flag_by_default` when ownership/control is unclear; intake asks ownership explicitly per vehicle group to pre-clear it. |
| 4.2 | "Do productions/tenants bring their own vehicles?" (film only) | ORG-050 boundary side; recorded as tenant-side, out of client scope | — | HUMAN | Tenant vehicles are out of scope; recording why is boundary judgment. |
| 4.3 | Fuel data availability: fuel-card records vs only mileage; biodiesel/blend flag per 3.3 | S1-MOB-460/470 route selectors; mileage path S1-MOB-120/260; blends S1-MOB-310 | J2-004 or mileage logs (J2-009) | AUTO | Schema supports fuel-based and distance/fuel-economy routes; intake picks based on documents the client actually has. |

## 5. Scope 1 screening — fugitives & process (per site)

| # | Intake item | Populates | Evidence triggered | Class | Reasoning |
|---|---|---|---|---|---|
| 5.1 | "AC or refrigeration systems your company maintains?" + equipment count/type | S1-FUG-100, S1-FUG-010 | J2-006, J2-008 | AUTO | Screening-factor route works from equipment data alone; material-balance route (S1-FUG-110) upgrades it when service records exist — intake asks "do you have service invoices?" to pick. |
| 5.2 | "Fire suppression systems using gas agents (not water sprinklers)?" | S1-FUG-050, S1-FUG-060/070 | J2-008 | AUTO | Plain-language wording must distinguish water sprinklers (no GHG) from clean-agent/CO2 systems. |
| 5.3 | "Purchase any industrial gases?" (CO2, welding gas, special effects gases) | S1-FUG-080, S1-FUG-120 | Purchase invoices (J2-003 pattern) | AUTO | Film-relevant: CO2/N2O for effects are Scope 1 when released. |
| 5.4 | "On-site wastewater treatment or other industrial processes?" | Screening only; if yes → escalate | J2-012 | HUMAN | Workbook flags process (PRC) calculations as unsupported for automation. Rare for SMEs; always goes to a human. |
| 5.5 | SF6 electrical equipment | NOT ASKED in v1 | — | — | Workbook flags full SF6 electrical accounting as unsupported for automation; SME prevalence ~0. Verifier-side only. |

## 6. Scope 2 (per site)

| # | Intake item | Populates | Evidence triggered | Class | Reasoning |
|---|---|---|---|---|---|
| 6.1 | Electricity accounts: supplier, account/meter numbers, how many meters | S2-MTR-020/030/040/080 | J2-002 ×12 months per meter | AUTO | Consumption quantities (S2-CON-020/025) come from extracted bills, never typed. Grid region (S2-MTR-070) derived from FAC-010 address. |
| 6.2 | "Shared building or shared meters with tenants/others?" + floor areas | S2-CON-055, S2-MTR-050 | Submeter reports (J2-009), lease terms (J2-007) | HUMAN | Allocation basis is judgment; human confirms before S1 processes dependent documents. |
| 6.3 | "Purchased steam, hot water, or chilled water?" | S2-MTR-030 carrier variants; S2-EFS-076/077 | District energy bills (J2-002 pattern) | AUTO | Asked per site as yes/no; never assumed. |
| 6.4 | "On-site solar or other generation? Sell any power back?" | OPB-020, S2-MTR-045/047, OPB-030 | Generation records (J2-009) | AUTO; HUMAN if selling | Selling energy or attributes creates double-counting risk (OPB-040) — that branch escalates. |
| 6.5 | "Bought renewable energy certificates or a green power product?" | S2-INS-010/020, market tier S2-EFS-110 | J2-019 | AUTO | Instruments activate market-based reporting alongside location-based (GHG Protocol Scope 2 Guidance dual reporting, conditional on instrument markets — applies in the US). J2-019's rules guard the classic error (RECs netted against Scope 1). |

## 7. Method routing defaults (the SME path cut — SYSTEM class, verifier-overridable)

| Source | Intake default route | Schema selector | Routes NOT exposed in intake |
|---|---|---|---|
| Stationary | `fuel_based_default`; `fuel_based_hhv` only if bills are in energy units | S1-STC-140 + selectors | CEMS, carbon-content lab analysis, complex waste gas, full fuel-inventory adjustment |
| Emergency generators | `activity_estimation` when unmetered | S1-STC-220 route | — |
| Mobile | fuel-based from fuel cards; distance × fuel-economy fallback | S1-MOB-460/470 | carbon-content routes |
| Fugitive | material balance from service records; screening factors fallback | S1-FUG-170 | SF6 electrical, leak-detection measurement routes |
| Scope 2 | billed consumption; location-based always + market-based when instruments exist | S2-CON-040 | — |

## 8. Provenance & data quality layer (every data point above)

| Universal | Film addition | Notes |
|---|---|---|
| Source document type; period covered; metered vs invoiced vs estimated | Lease/license agreements, submeter reports, generator rental invoices | Per the inventory-management-plan concept in the EPA/GHG Protocol guidance already cited in the workbooks. |
| **Uncertainty assessment** *(added in v0.2 — audit FAIL 2)*: each data point's metered/invoiced/estimated status rolls up to a category-level uncertainty rating; where quantitative estimation isn't feasible, a qualitative rating + justification is recorded | Same | ISO 14064-1 §8.3 requires uncertainty assessed at category level, with qualitative assessment justified when quantitative isn't feasible/cost-effective. The metered/invoiced/estimated field supplies ~80% of the input; this adds the roll-up + justification fields. |

## 9. Intake-only objects (no methodology home — new, live in `intake/`)

- Profile data-point **state machine**: unasked / asked / answered / unknown / not-applicable **(split in v0.2: "screened, not present" completeness status vs genuine exclusion)** / pending-documents / escalated / resolved
- **Escalation records** — candidate pattern to reuse: `reference-data/config/libraries/gap_ticket_schema.json`
- **Question content**: plain-language wording, explainers, film vocabulary overlay, per data point
- **Org/user/auth** (magic link), site records linking to FAC-010; responsible-party contact (1.2)

---

## Self-check & audit trail

**v0.1 verification:** every General, S1-STC, S1-MOB, S1-FUG, S2 field ID and all 20 J2 evidence types read directly from repo files; EPA citations taken from the workbooks' own Source_Citation columns; GHG Protocol Scope 2 dual-reporting condition verified against the Scope 2 Guidance.

**v0.2 — ISO 14064-1:2018 alignment audit (no-ai-slop, founder-reviewed, all findings accepted):**
1. Standards-basis section added (Scope ↔ ISO category correspondence; ISO removed scope terminology in 2018)
2. Uncertainty assessment added to provenance layer (ISO §8.3)
3. Significance criteria for excluded indirect categories added to boundary block (2.7)
4. Biogenic fuel screening question added (3.3), activating existing S1-STC-300/S1-MOB-310 routes
5. "Screened, not present" completeness status split from EXC-010 exclusions (3.4, §9)
6. Responsible party added to seed form (1.2)
7. Consolidation note: ISO permits other documented, justified approaches beyond the three named

**Assumptions still needing expert sign-off (Todd):** SME defaults for consolidation (2.1), base year (2.4), GWP/gas universe (2.6), significance-criteria template (2.7), method-route defaults (§7).

**Known integration caveats (from the workbooks' own flag sheets):** General MTH-020 key, PER-020 usage-based allocation, gas-universe alignment, and formal GEN versioning listed as open P0 items; Scope 2 not yet migrated to the final shared-key/edge contract. Claire to confirm before Aug 17 which remain open in code.

**Not yet verified:** Cross_Layer_Edge row-level details; Vocabulary Library contents (needed before question wording is written).
