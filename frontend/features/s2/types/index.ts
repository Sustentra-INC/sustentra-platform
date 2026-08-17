// Sustentra · Subsystem 2 · front-end types. Build spec §8.
// Every enumeration carries all of its values, including those the current backend
// cannot produce. An unreachable value costs one line; a missing one is invisible until it matters.

export type ReviewState =
  | 'not examined' | 'examination in progress' | 'examined — no exceptions'
  | 'examined — findings raised' | 'examination invalidated'

export type EvidenceState =
  | 'no evidence held' | 'requested' | 'partially held' | 'evidence held' | 'unobtainable'

export type ClosureBasis =
  | 'evidence examined' | 'established by other procedure'
  | 'unresolved, below threshold' | 'unresolved, escalated'

export type FindingType = 'clarification request' | 'misstatement' | 'nonconformity'

export type FindingState =
  | 'raised' | 'put to client' | 'corrected' | 'satisfied'
  | 'uncorrected — declined' | 'uncorrected — no response' | 'withdrawn'

export type RequestState =
  | 'drafted' | 'sent' | 'partially answered' | 'answered' | 'superseded' | 'withdrawn'

export type ActionWith =
  | 'verification team' | 'responsible party' | 'independent reviewer' | 'none outstanding'

export type RequirementGroup = 'activity' | 'factors' | 'boundary' | 'calculation'

export interface InventoryLine {
  id: string; facility: string; scope: 1 | 2; category: string
  quantityTCO2e: number; requirementIds: string[]
}

export interface Requirement {
  id: string; lineId: string; fieldId: string; label: string; definition: string
  group: RequirementGroup; grain: string; valueOrigin: string
  evidenceState: EvidenceState; reviewState: ReviewState; closureBasis?: ClosureBasis | null
  findingIds: string[]; assignedTo?: string | null
  performedBy?: string | null; performedAt?: string | null; technique?: string | null
  blocksCount: number
  invalidatedBy?: 'restatement' | 'new evidence' | 'changed selection'
  invalidatedAt?: string; unobtainableReason?: string
}

export interface Evidence {
  documentId: string; page?: number; snippet?: string
  value?: string | number; unit?: string
  approvedBy: string; approvedAt: string; governs: boolean
}

export interface Finding {
  id: string; type: FindingType; lineId: string; fieldId?: string
  summary: string; detail?: string
  magnitude?: number; magnitudeBasis?: string   // misstatements only
  criterion?: string                            // nonconformities only
  state: FindingState
  communicatedAt?: string; correctedAt?: string; refusalReason?: string
  raisedBy: string; raisedAt: string
}

export interface Ask { canonicalType: string; wording: string; satisfiesFieldIds: string[] }

export interface RequestRecord {
  id: string; state: RequestState; recipient?: string | null
  sentAt?: string; dueAt?: string; asks: Ask[]
  itemsCovered: number; itemsSatisfied: number
}

export interface DocumentRecord {
  id: string; name: string; canonicalType: string; pages: number
  receivedAt: string; from: string; satisfiesFieldIds: string[]
  lineId?: string | null; state: 'in extraction' | 'in review' | 'approved' | 'needs triage'
  partial?: boolean; unprompted?: boolean
  isInventorySource?: boolean; isProfileSource?: boolean
}

export interface Procedure {
  id: string; name: string; scopeNote: string; expectation: string
  expected: string; reported: string; difference?: string
  status: 'consistent' | 'investigate' | 'below threshold' | 'not covered'
}

export interface ChangeItem {
  kind: 'restatement' | 'evidence arrived' | 'colleague' | 'time passed'
  title: string; detail?: string; action?: { label: string; href: string }
  occurredAt?: string; severity: 'high' | 'medium' | 'low'
}
