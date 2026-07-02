# GitHub Push Readiness Report

## Summary
- Safe to push: no (needs fixes)
- Biggest blockers:
  - Folder is not initialized as a Git repository.
  - requirements.txt is missing for deployment packaging.
  - Potential secret indicators were found in files that are not currently ignored.
- Recommended next action: initialize git, tighten ignore rules, add requirements.txt, then re-run this audit.

## Git status
- Git repo detected: no
- git rev-parse --is-inside-work-tree returned: not a git repository
- Because git is not initialized, tracked/untracked status cannot be determined.
- .env state: ignore pattern exists in .gitignore (tracking state unknown)
- .venv/ state: ignore pattern exists in .gitignore (tracking state unknown)
- backups/ state: no ignore pattern found in .gitignore (tracking state unknown)

## Ignore rules
- .gitignore present: yes
- Required patterns present: 3/7
  - present: .env
  - present: .venv/
  - present: __pycache__/
  - missing: *.pyc
  - missing: .streamlit/secrets.toml
  - missing: backups/
  - missing: *.backup*
- Backup secret indicator check: potential indicators found under backups/
  - backups/20260619_143340/src/api/rag_client.py | keys: Authorization, RAG_API_KEY

## Secret scan (sanitized)
- Secret values are intentionally redacted from this report.
- Potential secret indicator files: 7
  - .env | keys: OPENAI_API_KEY, RAG_API_KEY | git_state: unknown_not_git_repo | ignore_pattern_state: ignored_by_pattern
  - .env.example | keys: OPENAI_API_KEY, RAG_API_KEY | git_state: unknown_not_git_repo | ignore_pattern_state: not_ignored_by_current_patterns
  - PLAN (2).md | keys: OPENAI_API_KEY | git_state: unknown_not_git_repo | ignore_pattern_state: not_ignored_by_current_patterns
  - backups/20260619_143340/src/api/rag_client.py | keys: Authorization, RAG_API_KEY | git_state: unknown_not_git_repo | ignore_pattern_state: not_ignored_by_current_patterns
  - docs/github_push_readiness_report.md | keys: AUTH_BEARER, OPENAI_API_KEY, RAG_API_KEY | git_state: unknown_not_git_repo | ignore_pattern_state: not_ignored_by_current_patterns
  - pages/5_Auditor_Chat.py | keys: RAG_API_KEY | git_state: unknown_not_git_repo | ignore_pattern_state: not_ignored_by_current_patterns
  - src/api/rag_client.py | keys: Authorization, RAG_API_KEY | git_state: unknown_not_git_repo | ignore_pattern_state: not_ignored_by_current_patterns
- Notes:
  - Findings above include identifier-name matches (for example, variable names in source code and this report), not confirmed secret values.
  - No raw secret values were printed during this audit.

## Large files
- Files >10MB: 0
- Files >50MB: 0
- Files >100MB: 0

## Deployment readiness
- app.py: present
- requirements.txt: missing
- .streamlit/config.toml: present
- .env.example: present
- README.md: missing
- data/demo/mock_outputs/mock_analysis_response.json: present
- config/libraries/evidence_type_library.json: present
- config/libraries/formula_library.json: present
- config/libraries/emission_factor_library.json: present
- config/libraries/gap_ticket_schema.json: present
- Import usage scan (BOM-safe parser):
  - streamlit: used
  - pandas: used
  - jsonschema: used
  - dotenv: used
  - httpx: used
  - requests: used
  - openpyxl: not_detected
  - boto3: used
  - openai: used

## Syntax checks
- Files checked: 13
- OK: 13
- Missing: 0
- Errors: 0
- Per-file results:
  - app.py: ok
  - pages/1_Upload_and_Analyze.py: ok
  - pages/2_Evidence_Review.py: ok
  - pages/3_Findings_Register.py: ok
  - pages/4_Finding_Detail.py: ok
  - pages/5_Auditor_Chat.py: ok
  - src/api/rag_client.py: ok
  - src/api/mock_client.py: ok
  - src/api/adapters.py: ok
  - src/ui/state.py: ok
  - src/ui/components.py: ok
  - src/ui/tables.py: ok
  - src/ui/formatting.py: ok

## Recommended fixes before push
- Initialize git in this folder and review staged files before first commit.
- Add requirements.txt for deployment/runtime reproducibility.
- Add or tighten ignore rules before commit:
  - *.pyc
  - .streamlit/secrets.toml
  - backups/
  - *.backup*
- Re-check files containing secret-like identifiers before committing, especially .env.example, PLAN (2).md, and backups/.
