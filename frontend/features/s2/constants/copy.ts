// Sustentra · Subsystem 2 · copy
// NO state or halt string may exist as a literal anywhere else in src/.
// Build spec §6. Enforced by the lint rule in §6 of the spec.

export const REVIEW_STATE = {
  notExamined:   'not examined',
  inProgress:    'examination in progress',
  noExceptions:  'examined — no exceptions',
  findingsRaised:'examined — findings raised',
  invalidated:   'examination invalidated',
} as const

export const EVIDENCE_STATE = {
  none:      'no evidence held',
  requested: 'requested',
  partial:   'partially held',
  held:      'evidence held',
  unobtainable: 'unobtainable',
} as const

export const CLOSURE_BASIS = {
  evidenceExamined:  'evidence examined',
  otherProcedure:    'established by other procedure',
  belowThreshold:    'unresolved, below threshold',
  escalated:         'unresolved, escalated',
} as const

export const FINDING_TYPE = {
  clarification: 'clarification request',
  misstatement:  'misstatement',
  nonconformity: 'nonconformity',
} as const

export const FINDING_STATE = {
  raised:      'raised',
  putToClient: 'put to client',
  corrected:   'corrected',
  satisfied:   'satisfied',
  declined:    'uncorrected — declined',
  noResponse:  'uncorrected — no response',
  withdrawn:   'withdrawn',
} as const

export const REQUEST_STATE = {
  drafted:   'drafted',
  sent:      'sent',
  partial:   'partially answered',
  answered:  'answered',
  superseded:'superseded',
  withdrawn: 'withdrawn',
} as const

export const ACTION_WITH = {
  team:     'verification team',
  client:   'responsible party',
  reviewer: 'independent reviewer',
  none:     'none outstanding',
} as const

export const GROUP = {
  activity:    'Activity',
  factors:     'Factors and properties',
  boundary:    'Boundary and completeness',
  calculation: 'Calculation',
} as const

export const GROUP_HINT = {
  activity:    'how much happened',
  factors:     'what converts activity into emissions',
  boundary:    'whether it is ours, and whether it is all here',
  calculation: 'how the number was assembled',
} as const

// The thirteen ISO 14064-3 §5.3 techniques. The first four are offered at limited assurance.
export const TECHNIQUES = [
  'inquiry', 'analytical testing', 'examination', 'cross-checking',
  'observation', 'confirmation', 'recalculation', 'retracing', 'tracing',
  'control testing', 'sampling', 'estimate testing', 'reconciliation',
] as const
export const TECHNIQUES_LIMITED = TECHNIQUES.slice(0, 4)

export const CONTAINER = {
  noInventory:      'No inventory has been received',
  noInventoryHint:  'The engagement is set up but no GHG accounting workbook has been submitted.',
  noneExamined:     (lines: number, total: string) => `${lines} lines · ${total} tCO₂e · none examined`,
  noneExaminedHint: 'No work has been done yet. This does not mean nothing is wrong.',
  filteredNone:     'No lines match',
  filteredNoneHint: 'Clear the filters to see the full register.',
  errorTitle:       'Requirements could not be loaded',
  errorHint:        (at: string) => `Showing the reported inventory from the last successful run, ${at}. Requirement states may be out of date.`,
  degraded:         (n: number) => `${n} of 8 lines loaded`,
  degradedHint:     (names: string) => `${names} unavailable.`,
  blocked:          'Fixture mode: recording is not durable',
  blockedHint:      'Actions route through the S2 persistence boundary, but this local review state resets outside this session.',
  complete:         'All 8 lines examined',
  completeHint:     'This is not a conclusion. Uncorrected misstatements and nonconformities carry to the conclusion for evaluation against materiality.',
  loadingLabel:     'Loading requirements',
} as const

export const ACTIONS = {
  request:       'Request',
  unobtainable:  'Unobtainable',
  byProcedure:   'By procedure',
  chase:         'Chase',
  reExamine:     'Re-examine',
  open:          'Open',
  assignToMe:    'Assign to me',
  recordNext:    'Record & next',
  recordStay:    'Record & stay',
  skip:          'Skip',
  addNote:       'Add a note',
  raiseFinding:  'Raise a finding',
  putToClient:   'Put to client',
  withdraw:      'Withdraw',
  acceptSufficient: 'Accept as sufficient',
  requestMissing:   'Request the missing part',
  markAllSeen:   'Mark all seen',
  clearFilters:  'Clear filters',
  exportForFile: 'Export for the file',
} as const

export const REFUSALS = {
  noTechnique: 'Record a technique before concluding — ISO 14064-3 §5.4.4(d) requires the activity performed.',
  noRationale: 'A finding needs a rationale before it can be raised.',
  reviewerSameAsPerformer: 'The reviewer must be someone other than the person who performed the work.',
} as const

// Words that must never appear in rendered copy. Lint against this list.
export const BANNED = [
  'passed', 'verified', 'clean', 'OK', 'no issues', 'all clear', 'awaiting', 'pending',
  'outstanding', 'issue', 'gap', 'exception', 'done', 'stale', 'reopened', 'notified',
  'flagged', 'not applicable', 'severity', 'high', 'medium', 'low',
] as const
