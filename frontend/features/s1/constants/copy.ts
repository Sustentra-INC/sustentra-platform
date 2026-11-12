export const HALT_REASONS = {
  unsupportedFormat: "File format not supported.",
  unreadable: "File could not be read.",
  ocrFailed: "Text could not be extracted. Request a better scan, or enter values manually.",
  ocrRequired: "Photo or scan: its text is read once OCR is switched on. Ask for a text PDF meanwhile.",
  passwordProtected: "Password-protected: ask the client for a copy without a password.",
  noTemplate: "No extraction template exists for this document type.",
  typeUnknown: "Document type not recognised. Choose its type on Evidence and it is read again.",
  multiFacility: "Multi-facility document · splitting is not supported in V1.",
  pipeline: "Processing failed. Retry available.",
  documentTooLong: "Too many pages to read in one file. Split it into smaller files and upload them separately.",
} as const;

/** Claude's reading of a document's type (backend services/ai_routing.py). */
export const AI_TYPE = {
  suggested: "Type suggested by Claude, please confirm",
  disagreesOn: (rulesType: string, claudeType: string) =>
    `The rules chose ${rulesType}, but Claude read the first pages as ${claudeType}. The type was not changed.`,
} as const;

/** Claude's reading of a value (backend services/ai_extraction.py). */
export const AI_VALUE = {
  suggested: "Suggested by Claude",
  suggestedHelp: "Claude read this where the rules found nothing. Check it against the page, then accept or correct it.",
  conflict: "Claude read two different values here",
  conflictHelp: "Claude read another value for this field elsewhere in the document. Check the page.",
  disagrees: "Claude read a different value here",
  disagreesHelp: "The rules read the value above and kept it. Claude read another: check the page.",
  readBy: "Read by Claude",
} as const;

export const EXACT_COPY = {
  noEvidenceYet: "No evidence yet",
  noDocumentsMatch: "No documents match this filter",
  filterActive: "Counts above are engagement-wide. The table below is filtered.",
  railMagnitude: "not yet evaluated",
  sourceLocationMissing: "page location not available",
  valueAbsent: "not found",
  dependencyBlocked:
    "In-scope field list is not available yet. Completeness will render here when the dependency is available.",
  manualEntryHeader: "Opened for manual entry · no machine read this document.",
  manualEntryFieldList:
    "Every field is empty and enterable · extraction never ran on this document, so there is no machine reading to check. The field list is the one this document type is defined as carrying.",
  manualEntrySource:
    "No extracted span for any field on this document · extraction was blocked, so nothing was read. Values keyed here are marked human-keyed permanently.",
  manualEntryInput:
    "Keying the value is the review · you are the source, so there is nothing for a machine reading to be checked against. The field goes straight to reviewed and is marked human-keyed permanently.",
  glossaryIntro:
    "The words are the contract. These terms are not interchangeable, and this is the only place they are defined · no search, no articles, no categories, because a stale explanation is worse than none.",
  manualEntryNoFieldList: "No field list is defined for this document type yet.",
} as const;
