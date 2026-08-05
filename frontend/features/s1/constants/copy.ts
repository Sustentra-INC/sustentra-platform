export const HALT_REASONS = {
  unsupportedFormat: "File format not supported.",
  unreadable: "File could not be read.",
  ocrFailed: "Text could not be extracted. Request a better scan, or enter values manually.",
  noTemplate: "No extraction template exists for this document type.",
  multiFacility: "Multi-facility document — splitting is not supported in V1.",
  pipeline: "Processing failed. Retry available.",
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
} as const;
