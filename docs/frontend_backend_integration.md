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
```

The S1 calls are same-origin (`/api/v1/*`, FE-007), so there is no URL to point: in dev `next.config` proxies `/api/v1` to `BACKEND_INTERNAL_URL` (default `http://localhost:8000`), in prod Caddy routes it. Flip to `backend`, and the screens that have endpoints light up with real data. **Nothing else on the frontend needs to change** to go live — that's the whole point of the seam.

## The seam (where FE talks to BE)

- `frontend/features/s1/api/s1Backend.ts` — all backend calls (the functions below).
- `frontend/features/s1/adapters/evidenceAdapter.ts`, `fieldAdapter.ts` — map backend JSON → the view models the screens render. **These adapters are the contract** — they show exactly what fields the frontend expects back.
- Detailed plan (storage, work items): `frontend/features/s1/docs/S1_BACKEND_INTEGRATION_PLAN.md`.

## Function → endpoint → page map (what to implement against)

Every call the frontend makes, the function that makes it, and which screen it powers. All in `features/s1/api/s1Backend.ts` unless noted. Since FE-007 every call goes through the same-origin cookie client `lib/api.ts` (`api` / `apiMaybe`, URLs via `apiPath`): the browser sends the `__Host-session` cookie, `next.config` rewrites `/api/v1/*` to the backend in dev and Caddy routes it in prod.

| Function (frontend) | Calls (backend) | Method | Powers |
|---|---|---|---|
| `listWorkspaceEvidence(engagementId)` | `/api/v1/engagements/{engagementId}/documents` then per-doc `/api/v1/pipeline/evidence/{evidenceId}/latest-run`, `/api/v1/documents/{documentId}/extraction-result/latest`, `/api/v1/documents/{documentId}/reviews` | GET | **Evidence workspace** (and seeds Extraction review) |
| `uploadDocument(engagementId, file)` | `/api/v1/engagements/{engagementId}/documents/upload` (multipart) | POST | **Upload page** |
| `processDocument(documentId)` | `/api/v1/documents/{documentId}/pipeline/process` | POST | **Upload / Evidence** (kick off extraction) |
| `submitFieldReview({ evidenceId, fieldName, decision, reviewedValue, candidate })` | `/api/v1/evidence/{evidenceId}/fields/{fieldName}/review` | PUT | **Extraction review** (accept / correct / reject / needs-more) |
| `downloadUrl(documentId)` | `/api/v1/documents/{documentId}/download` | GET (url) | **Extraction review** (original PDF) |
| `inlineDocumentUrl(documentId)` *(adapter)* | `/api/v1/documents/{documentId}/preview` | GET (url) | **Extraction review** (inline preview) |
| `getSignedInUser()` | `/api/v1/auth/me` | GET | **Workpaper load** (session check before any data) |
| `userFacingApiError(error)` | — | — | error-message helper (no call) |
| `isSessionEnded(error)` / `signInAgainPath(next)` | — | — | 401 handling (see Auth note) |

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
| Evidence workspace | `/api/v1/engagements/{id}/documents` | GET |
| Upload | `/api/v1/engagements/{id}/documents/upload` | POST |
| Evidence / Extraction | `/api/v1/pipeline/evidence/{id}/latest-run` | GET |
| Extraction review | `/api/v1/documents/{id}/extraction-result/latest` *(MVP-34 — 404 until built; read as "no result yet")* | GET |
| Run pipeline | `/api/v1/documents/{id}/pipeline/process` | POST |
| Extraction review (PDF) | `/api/v1/documents/{id}/download`, `/api/v1/documents/{id}/preview` *(MVP-34)* | GET |
| Review decisions | `/api/v1/documents/{id}/reviews` | GET |
| Accept / correct a field | `/api/v1/evidence/{id}/fields/{field}/review` | PUT |

**Jack/Jerome ask:** confirm these return the shapes the adapters expect (see `evidenceAdapter.ts` / `fieldAdapter.ts`), ensure they're tenant-scoped once auth is in, then we flip `DATA_MODE=backend` for these screens.

## Ports with NO backend yet (fixture-only — build or keep as demo)

| Screen / feature | What it needs | Status |
|---|---|---|
| **Verification numbers** (reported vs recomputed, materiality, per-row working) | The **GHG calculation engine** (activity × emission factor → CO₂e) + **Scope 2** location/market + emission-factor library | **Not built** (S2 roadmap PR12). This is the big one — matches Claire's combustion flowcharts. |
| **Check coverage** | input-readiness computation | Partial (S2 completeness tracker exists; needs an endpoint) |
| **Evidence requests** (client email) | a requests model + send path | Needs backend + `EMAIL-001` |
| **Dashboard** (KPIs, charts) | aggregate endpoints (counts, coverage %, phase) | Not built — decide build vs. demo-only |
| **AI assistant** | a real assistant/LLM endpoint | Backend has a placeholder; decide real vs. canned |
| **Setup — scope & assurance fields** (`dataScope`, `assuranceStandard`, `assuranceLevel`, `materialityThreshold`) | persisted with the engagement | **Done** (S1-BE-002, engagement `settings`) |

## Auth / tenancy note

> **SEC-001 (done):** every `/api/v1` S1 call requires the `__Host-session` cookie (401 without it) and is scoped to the caller's org (another org's records answer 404). `uploaded_by` / `reviewer_id` in request bodies are ignored; the signed-in user is recorded. A `provider_admin` can read but gets 403 on writes. The old root `/v1` routes are local-dev only.

> **FE-007 (done):** the S1 seam uses the same-origin cookie client, so no request goes out without the session (local dev included, via the `next.config` rewrite — no `credentials: "include"` or CORS needed). On load the workpaper calls `/api/v1/auth/me`; any 401 means the session ended:
> - the login page remembers the realm the user last signed in to (`features/auth/lastRealm.ts`, localStorage: `org:<slug>` or `provider` — no secrets), so the workpaper sends them to `/org/<slug>/login?next=/` (or `/provider-admin/login?next=/`);
> - when the browser has no remembered realm it shows a small "Sign in to continue" panel asking for the organization;
> - login pages honour `?next=` for same-origin paths only.

## TL;DR for the backend team

1. The frontend is done and wired for the **evidence → extraction → review** chain — those endpoints already exist, so that half can go live now (confirm shapes + tenant-scope).
2. The **calculation/verification** half (and requests, dashboard, assistant) is fixture-only until the backend builds it — the calc engine + Scope 2 is the critical dependency.
3. Flipping `NEXT_PUBLIC_S1_DATA_MODE=backend` is the only switch needed on our side.

## S1-BE-001: extraction result, download, preview (done)

- `GET /api/v1/documents/{id}/extraction-result/latest` → `{evidence_id, document_id, pipeline_run_id, canonical_type_id, status, candidate_count, items, created_at}`; `items` are the extraction candidates `fieldAdapter.ts` reads. Every persisted pipeline run stores its candidates (`local-data/extraction-results/extraction_results.jsonl`); "latest" is the newest run for that document (a halted run gives `items: []`). 404 before the first persisted run.
- `GET /api/v1/documents/{id}/download` → the original file as an attachment.
- `GET /api/v1/documents/{id}/preview` → the file inline, **PDF / PNG / JPEG only** (415 otherwise).
- All three: session required, org-scoped (404 for unknown or another org's document, like SEC-001).
- The served `Content-Type` comes from the file's bytes, not the uploaded `mime_type`, and responses carry `nosniff`, so an HTML/SVG upload can never run as a page on the app's origin.
- Embedding: the preview may be framed by the app only (`X-Frame-Options: SAMEORIGIN`, `frame-ancestors 'self'`); Caddy's `DENY` / `frame-ancestors 'none'` are defaults the API overrides for this route. Use an `<iframe>` (or `<img>`) — the page CSP has `object-src 'none'`, so `<object>`/`<embed>` are blocked.

## S1-BE-002: engagements (done)

- Stored in Postgres (`engagements`, migration 0008) with Row-Level Security: a row is visible only in its org's tenant context or provider scope. The app role cannot delete; engagements are archived (`status`).
- `GET /api/v1/engagements` (active ones, newest first; `?include_archived=true`), `POST /api/v1/engagements` (`{name, client_name?, reporting_period_start?, reporting_period_end?, settings?}` → 201), `GET` / `PATCH /api/v1/engagements/{id}` (partial; `settings` is replaced whole). Org users read/write their own org's; provider_admin reads all (`?org_id=` to filter) and gets 403 on writes; another org's id is 404. Create/update/archive write audit events (field names only).
- `settings` holds the rest of Setup using the frontend's names (`facilities`, `regulation`, `clientContact`, `engagementTeam`, `dataScope`, …); unknown keys are 422, max 64 KB.
- Frontend (`features/s1/api/engagements.ts`, `components/EngagementPicker.tsx`): Setup lists the org's engagements, creates new ones and picks one; edits autosave (~0.7 s after typing stops); the last pick is remembered per browser. Uploads and the Evidence Workspace use the picked engagement's id; uploading without one asks the user to pick or create it first.
- Document listings now return the latest version of each document (the store is append-only, so a processed upload used to show up once per status change).
