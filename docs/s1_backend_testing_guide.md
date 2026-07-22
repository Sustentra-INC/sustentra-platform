# S1 Backend Testing Guide (Engineering)

This guide is for engineering teammates validating the current local S1 backend workflow.

Scope of this guide:

- Local backend setup and test execution.
- Local API/manual flow for upload -> pipeline -> review -> approved evidence.
- Synthetic smoke script execution without requiring a running HTTP server.

Out of scope:

- Production deployment hardening.
- Compliance conclusions.
- Calculation, reconciliation, and gap analysis validation.

## 1) Fresh Clone Setup

## Python version note

Use Python 3.11+ (3.12 recommended for current local test flow).

PowerShell:

```powershell
python --version
```

Bash:

```bash
python --version
```

## Create and activate virtual environment

PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Bash:

```bash
python -m venv .venv
source .venv/bin/activate
```

## Install dependencies

PowerShell:

```powershell
python -m pip install -r backend/requirements.txt
```

Bash:

```bash
python -m pip install -r backend/requirements.txt
```

## Run backend tests

PowerShell:

```powershell
python -m pytest -q backend/tests
```

Bash:

```bash
python -m pytest -q backend/tests
```

## 2) Start FastAPI Backend And Swagger

Start server:

```bash
uvicorn backend.app.main:app --reload
```

Open docs:

```text
http://localhost:8000/docs
```

## 3) Generate Synthetic Evidence

Generate local fake evidence input for S1 testing:

PowerShell:

```powershell
python backend/scripts/generate_synthetic_evidence.py
```

Bash:

```bash
python backend/scripts/generate_synthetic_evidence.py
```

Default output path:

```text
local-samples/generated/synthetic_fuel_bill.txt
```

Optional custom output:

```bash
python backend/scripts/generate_synthetic_evidence.py --output-dir local-samples/generated --file-name demo_bill.txt --overwrite
```

## 4) Run Backend S1 Smoke Script (Service Layer, No HTTP Server)

This script calls backend services directly and exercises upload -> pipeline -> review -> approved evidence.

PowerShell:

```powershell
python backend/scripts/backend_s1_smoke.py --generate-sample --clean-run
```

Bash:

```bash
python backend/scripts/backend_s1_smoke.py --generate-sample --clean-run
```

Common options:

- `--sample-file`
- `--generate-sample`
- `--engagement-id`
- `--canonical-type-id`
- `--reviewer-id`
- `--clean-run`

## 5) Manual API Flow (curl)

Use fake IDs and synthetic file names.

Flow:

1. Upload document.
2. Process uploaded document.
3. Inspect extraction candidates.
4. Submit review decision.
5. Project approved evidence.
6. Retrieve latest approved evidence.

### 5.1 Upload document

PowerShell (use `curl.exe` to avoid PowerShell alias behavior):

```powershell
curl.exe -X POST "http://localhost:8000/v1/engagements/eng-smoke-001/documents/upload" ^
  -F "file=@local-samples/generated/synthetic_fuel_bill.txt" ^
  -F "document_role=source_evidence" ^
  -F "uploaded_by=smoke-reviewer@example.com"
```

Bash:

```bash
curl -X POST "http://localhost:8000/v1/engagements/eng-smoke-001/documents/upload" \
  -F "file=@local-samples/generated/synthetic_fuel_bill.txt" \
  -F "document_role=source_evidence" \
  -F "uploaded_by=smoke-reviewer@example.com"
```

Capture `document_id` and `evidence_id` from the response.

### 5.2 Process uploaded document

```bash
curl -X POST "http://localhost:8000/v1/documents/doc_fake_001/pipeline/process" \
  -H "Content-Type: application/json" \
  -d '{
    "canonical_type_id_override": "CT-S1-FUELQTY",
    "persist_run": true
  }'
```

### 5.3 Inspect extraction candidates

The process response includes:

- `extraction_result.items` (candidate list)
- `pipeline_run` (stage/status/count summary)

### 5.4 Submit review decision

```bash
curl -X PUT "http://localhost:8000/v1/evidence/ev_fake_001/fields/fuel_quantity_mmbtu/review" \
  -H "Content-Type: application/json" \
  -d '{
    "decision": "accepted",
    "reviewer_id": "smoke-reviewer@example.com",
    "candidate": {
      "candidate_id": "candidate::ev_fake_001::doc_fake_001::fuel_quantity_mmbtu",
      "evidence_id": "ev_fake_001",
      "document_id": "doc_fake_001",
      "field_name": "fuel_quantity_mmbtu",
      "display_label": "Fuel Quantity",
      "raw_value": "28,100 MMBtu",
      "normalized_value": 28100,
      "unit": "MMBtu",
      "confidence": 0.9,
      "validation_flags": [],
      "source_reference": {
        "source_reference_id": "SRC-demo-1",
        "document_id": "doc_fake_001",
        "page_number": 1,
        "sheet_name": null,
        "cell_or_range": null,
        "text_snippet": "Total Usage: 28,100 MMBtu",
        "bounding_box": null,
        "parser_block_ids": ["text_parser-p1-b1"],
        "source_kind": "page_text"
      }
    }
  }'
```

### 5.5 Project approved evidence

```bash
curl -X POST "http://localhost:8000/v1/evidence/ev_fake_001/approved-evidence/project" \
  -H "Content-Type: application/json" \
  -d '{
    "engagement_id": "eng-smoke-001",
    "evidence_type": "CT-S1-FUELQTY"
  }'
```

### 5.6 Retrieve latest approved evidence

```bash
curl -X GET "http://localhost:8000/v1/evidence/ev_fake_001/approved-evidence/latest"
```

## 6) Safe Cleanup

Local runtime/sample directories are intentionally ignored by git.

PowerShell:

```powershell
Remove-Item -Recurse -Force local-data, local-samples/generated
```

Bash:

```bash
rm -rf local-data local-samples/generated
```

## 7) Troubleshooting

## `python-multipart` missing

Symptom: FastAPI raises form/multipart import/runtime error.

Fix:

```bash
python -m pip install python-multipart
```

## FastAPI import errors

Checks:

- Run commands from repository root.
- Confirm virtual environment is active.
- Reinstall requirements.

## Wrong Python interpreter

Checks:

PowerShell:

```powershell
Get-Command python
python -c "import sys; print(sys.executable)"
```

Bash:

```bash
which python
python -c "import sys; print(sys.executable)"
```

## `local-data` not created

`local-data/` is created during upload/process/smoke runtime writes.
If it does not exist, run:

```bash
python backend/scripts/backend_s1_smoke.py --generate-sample
```

## `local-data` appears in `git status`

Expected behavior is that `local-data/` is ignored.

If files were staged accidentally:

```bash
git restore --staged local-data local-samples
```

## Pipeline returns `partial`

Common causes:

- No confident canonical type from classification.
- No override provided for canonical type.
- Target planning/candidate generation skipped for that run.

Try passing `canonical_type_id_override` in process request.

## Low found rate / missing candidates

Common causes:

- Wrong canonical type for the document.
- Missing anchors/values in document text.
- Parser output has limited usable blocks/tables/key-value pairs.

Actions:

- Re-check `canonical_type_id_override`.
- Review `pipeline_run` warnings.
- Review parser/extraction smoke reports under `local-samples/`.
