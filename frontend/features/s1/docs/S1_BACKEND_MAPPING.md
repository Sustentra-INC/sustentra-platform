# S1 Backend Mapping

This document records how current backend responses map into Subsystem 1 view
models. React components should consume the S1 view models, not backend DTOs.

| S1 field | Backend source | Status | Notes |
|---|---|---:|---|
| `documentId` | document API `document_id` | connected | Normalized in `adapters/evidenceAdapter.ts`. |
| `filename` | document API `file_name` | connected | Displayed in Evidence Workspace and Extraction Review queue. |
| `format` | document filename / MIME type | partial | Current adapter infers from filename; should use robust MIME mapping later. |
| `uploadedBy` | document API `uploaded_by` | partial | Current API provides a string, S1 expects an actor object. |
| `uploadedAt` | document API `uploaded_at` | connected | Timestamp is preserved. |
| `processingState` | document `processing_status` + pipeline run | partial | Backend vocabulary is mapped to S1 vocabulary; components do not render raw backend statuses. |
| `haltReason` | pipeline errors / parser failure reasons | partial | Exact S1 halt strings still need backend reason mapping. |
| `detectedType` | classification result `primary_canonical_type_id` / labels | partial | Current fixture uses display labels; backend mapping needs canonical label resolver. |
| `typeReviewBand` | classification status | partial | Needs S1 band mapping: `auto_accepted`, `needs_review`, `cannot_determine`. |
| `facilityState` | facility matcher | missing | Render `unresolved` with inline assignment until matcher/config API exists. |
| `facilityId` / `facilityName` | engagement config facilities | front-end only | Temporary `engagementConfig` fixture is the closed list. |
| `periodState` | parser output / engagement period | partial | Dates may be extractable, but engagement-period context is not wired. |
| `fieldsExpected` | extraction target count | partial | Pipeline run has `target_count`; exact document-type expected count needs adapter rules. |
| `fieldsExtracted` | pipeline run `found_candidate_count` | partial | Should exclude non-reviewable origins where applicable. |
| `relationships` | dedupe/supersession/conflict service | missing | Render fixture shape; backend support not present. |
| `documentProperties` | parser/classifier document properties | missing | Render fixture shape; backend support not present. |
| `reviewArea` / `note` | supportive evidence metadata | missing | Needs evidence-class flag and supportive evidence metadata path. |
| extraction field `fieldKey` | `resolveFieldKey(canonical_type_id, field_name)` | connected | `fieldKey` is opaque to components. |
| extraction field value/unit | extraction candidate `normalized_value` / `unit` | connected | Normalized in `adapters/fieldAdapter.ts`. |
| source snippet | extraction candidate `source_reference.text_snippet` | partial | Snippet context is available only when backend provides enough context. |
| source location | `SourceLocation` page/cell data | missing | S1 renders `page location not available`; never guesses page 1. |
| review status | review API / approved evidence projection | partial | Current UI uses local fixture/review state. |
| audit entries | dedicated audit API | blocked | Do not enable writes until audit persistence survives restart. |

## Boundary Rule

Backend terminology may appear inside adapters and backend-facing types. It must
be normalized before React components render it.

```
Backend API -> S1 adapter -> S1 view model -> React component
```

If a backend field is absent, render the intended S1 absence/dependency state
instead of hiding the surface.

## Dependency Matrix

| S1 UI requirement | Backend source | Adapter | Status |
|---|---|---|---:|
| Document identity | Document API | `evidenceAdapter` | ready |
| Upload metadata | Document API | `evidenceAdapter` | ready |
| Processing state | Document API + pipeline run | `evidenceAdapter` / future `processingAdapter` | partial |
| Halt reason | Pipeline errors / parser errors | `evidenceAdapter` | partial |
| Type detection | Classification result | future `classificationAdapter` | partial |
| Type review band | Classification result status | future `classificationAdapter` | partial |
| Facility resolution | Facility matcher / setup config | future `facilityAdapter` | missing |
| Facility closed list | Engagement setup | fixture accessor today | front-end only |
| Period resolution | Parser output + engagement period | future `periodAdapter` | partial |
| Field expected count | Extraction targets | future `fieldCountAdapter` | partial |
| Field extracted count | Extraction candidates | future `fieldCountAdapter` | partial |
| Relationship flags | Dedup/conflict service | future `relationshipAdapter` | missing |
| Document properties | Parser/classifier diagnostics | future `documentPropertyAdapter` | missing |
| Supportive evidence | Evidence-class metadata | future `supportiveEvidenceAdapter` | missing |
| Extraction queue | Extraction candidates + review decisions | `fieldAdapter` | partial |
| Source snippet | Extraction candidate source reference | `fieldAdapter` | partial |
| Source page/cell location | Extractor `location` | `fieldAdapter` | missing |
| Review state | Review API / approved evidence projection | future `reviewAdapter` | partial |
| Audit history | Persistent audit event storage | future `auditAdapter` | blocked |

## Audit Persistence Gate

Write actions remain intent-only until the backend can prove audit events survive
restart and include:

- actor
- timestamp
- old value
- new value
- document association
- field association when applicable
- bulk expansion into one persisted event per affected item

## Backend Mode Milestones

Backend integration should proceed in this order:

1. `fixture` / `backend` data-mode switch.
2. Engagement/project read APIs.
3. Document upload with persistent object storage.
4. Document metadata read APIs.
5. Pipeline status read APIs.
6. Extraction result read APIs.
7. Original document download/view endpoint.
8. Review decision writes where persistence already exists.
9. Dedicated audit event persistence.
10. Audit-required write actions.

Until steps 8-10 are complete, the frontend may show actions but must not imply
that audit-required edits are durably saved.
