# Frontend ↔ Backend Integration — the ports

**For:** Jack & Jerome (backend)  ·  **From:** Thanishque (frontend)  ·  **Date:** 2026-10-04
**Branch:** `integrate/demo-ui`

## What changed on the frontend

The real product frontend now **is** the demo UI. On branch `integrate/demo-ui` (off `main`):

- `/` → the full S1 audit **workpaper** (Setup, Upload, Evidence, Extraction review, Check coverage, Verification, Output, Dashboard, + the floating assistant). This is the polished demo, now the product home. Code lives in `frontend/features/s1/`.
- **Jerome's auth/tenancy pages are preserved** — `/login`, `/login/reset`, `/clients`, `/users`, `/account` still work exactly as before (moved into an `app/(admin)/` route group that keeps `AppShell`; URLs unchanged).
- Jack's old placeholder route stubs (`evidence-intake`, `extraction-review`, `calculation`, `gap-analysis`, `validation`, `audit-setup`, `assistant`) were removed — the workpaper supersedes them.
- Builds clean (`next build` ✓, TypeScript ✓). The workpaper currently runs on **fixtures**.

## The switch: fixtures → real data

One runtime flag decides where the workpaper's data comes from (`frontend/features/s1/pages/S1WorkpaperApp.tsx`):

```
NEXT_PUBLIC_S1_DATA_MODE=fixture   # current — hardcoded demo data (Cascade Provisions)
NEXT_PUBLIC_S1_DATA_MODE=backend   # calls the real API via the seam below
NEXT_PUBLIC_BACKEND_API_URL=https://<api-host>   # where the backend lives
```

Flip to `backend` + point the URL, and the screens that have endpoints light up with real data. **Nothing else on the frontend needs to change** to go live — that's the whole point of the seam.

## The seam (where FE talks to BE)

- `frontend/features/s1/api/s1Backend.ts` — all backend calls (the functions below).
- `frontend/features/s1/adapters/evidenceAdapter.ts`, `fieldAdapter.ts` — map backend JSON → the view models the screens render. **These adapters are the contract** — they show exactly what fields the frontend expects back.
- Detailed plan (storage, work items): `frontend/features/s1/docs/S1_BACKEND_INTEGRATION_PLAN.md`.

## Function → endpoint → page map (what to implement against)

Every call the frontend makes, the function that makes it, and which screen it powers. All in `features/s1/api/s1Backend.ts` unless noted.

| Function (frontend) | Calls (backend) | Method | Powers |
|---|---|---|---|
| `listWorkspaceEvidence(engagementId)` | `/v1/engagements/{engagementId}/documents` then per-doc `/v1/pipeline/evidence/{evidenceId}/latest-run`, `/v1/documents/{documentId}/extraction-result/latest`, `/v1/documents/{documentId}/reviews` | GET | **Evidence workspace** (and seeds Extraction review) |
| `uploadDocument(engagementId, file)` | `/v1/engagements/{engagementId}/documents/upload` (multipart) | POST | **Upload page** |
| `processDocument(documentId)` | `/v1/documents/{documentId}/pipeline/process` | POST | **Upload / Evidence** (kick off extraction) |
| `submitFieldReview({ evidenceId, fieldName, decision, reviewedValue, candidate })` | `/v1/evidence/{evidenceId}/fields/{fieldName}/review` | PUT | **Extraction review** (accept / correct / reject / needs-more) |
| `downloadUrl(documentId)` | `/v1/documents/{documentId}/download` | GET (url) | **Extraction review** (original PDF) |
| `inlineDocumentUrl(documentId)` *(adapter)* | `/v1/documents/{documentId}/preview` | GET (url) | **Extraction review** (inline preview) |
| `userFacingApiError(error)` | — | — | error-message helper (no call) |

**Adapters (the response contract):**
- `mapBackendDocumentToEvidenceItem(document, latestRun)` — backend document + pipeline run → an evidence row.
- `mapBackendCandidateToExtractedField(candidate, canonicalTypeId)` — an extraction candidate → a reviewable field (value, source snippet, confidence, bbox).
- `encodeReviewCandidateToken` / `decodeReviewCandidateToken` — stable id for a candidate across the review round-trip.
- `resolveCanonicalTypeDisplayName`, `mapHaltReason` — display helpers.

The field names these functions read/write are the contract — match them and the screens light up with zero frontend changes.

## Empty by default (no templated data)

In `backend` mode the frontend starts **completely empty**: no engagement, no documents, no evidence, no coverage/verification rows, and a Dashboard that shows empty states until real data arrives. There is no Cascade Provisions / demo data in this build. The user creates the engagement in Setup and uploads real documents, which flow through the functions above. (The old demo data only loads if `NEXT_PUBLIC_S1_DATA_MODE=fixture`, which production does not set.)

## Ports that are READY to wire (endpoints the FE already calls — and that exist in the S1 backend)

| Screen | Endpoint the frontend calls | Method |
|---|---|---|
| Evidence workspace | `/v1/engagements/{id}/documents` | GET |
| Upload | `/v1/engagements/{id}/documents/upload` | POST |
| Evidence / Extraction | `/v1/pipeline/evidence/{id}/latest-run` | GET |
| Extraction review | `/v1/documents/{id}/extraction-result/latest` | GET |
| Run pipeline | `/v1/documents/{id}/pipeline/process` | POST |
| Extraction review (PDF) | `/v1/documents/{id}/download`, `/v1/documents/{id}/preview` | GET |
| Review decisions | `/v1/documents/{id}/reviews` | GET |
| Accept / correct a field | `/v1/evidence/{id}/fields/{field}/review` | PUT |

**Jack/Jerome ask:** confirm these return the shapes the adapters expect (see `evidenceAdapter.ts` / `fieldAdapter.ts`), ensure they're tenant-scoped once auth is in, then we flip `DATA_MODE=backend` for these screens.

## Ports with NO backend yet (fixture-only — build or keep as demo)

| Screen / feature | What it needs | Status |
|---|---|---|
| **Verification numbers** (reported vs recomputed, materiality, per-row working) | The **GHG calculation engine** (activity × emission factor → CO₂e) + **Scope 2** location/market + emission-factor library | **Not built** (S2 roadmap PR12). This is the big one — matches Claire's combustion flowcharts. |
| **Check coverage** | input-readiness computation | Partial (S2 completeness tracker exists; needs an endpoint) |
| **Evidence requests** (client email) | a requests model + send path | Needs backend + `EMAIL-001` |
| **Dashboard** (KPIs, charts) | aggregate endpoints (counts, coverage %, phase) | Not built — decide build vs. demo-only |
| **AI assistant** | a real assistant/LLM endpoint | Backend has a placeholder; decide real vs. canned |
| **Setup — scope & assurance fields** (`dataScope`, `assuranceStandard`, `assuranceLevel`, `materialityThreshold`) | add these 4 fields to the engagement model so Setup persists | Small schema add |

## Auth / tenancy note

The workpaper currently has no login of its own (fixture demo). Once Jerome's auth lands, the product at `/` should sit behind the session guard like the admin pages, and the `/v1` calls above must be **tenant-scoped** (engagement/org filtered) so data is isolated. The seam already sends the bearer token via `lib/api/client.ts`.

> **SEC-001 (done):** every `/api/v1` S1 call now requires the `__Host-session` cookie (401 without it) and is scoped to the caller's org (another org's records answer 404). `uploaded_by` / `reviewer_id` in request bodies are ignored; the signed-in user is recorded. A `provider_admin` can read but gets 403 on writes. Same-origin `fetch` in prod sends the cookie automatically; local dev across ports needs `credentials: "include"` (FE-007).

## TL;DR for the backend team

1. The frontend is done and wired for the **evidence → extraction → review** chain — those endpoints already exist, so that half can go live now (confirm shapes + tenant-scope).
2. The **calculation/verification** half (and requests, dashboard, assistant) is fixture-only until the backend builds it — the calc engine + Scope 2 is the critical dependency.
3. Flipping `NEXT_PUBLIC_S1_DATA_MODE=backend` is the only switch needed on our side.
