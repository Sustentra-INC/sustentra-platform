# Free Staging Deployment

This path uses free tiers for a shared S1 staging app:

```
Vercel frontend
  -> Render backend
     -> Supabase Postgres
     -> Supabase Storage via S3-compatible API
     -> OpenAI extraction API
```

## 1. Supabase

Create a Supabase project, then create one Storage bucket:

```text
sustentra-documents
```

In Supabase Storage settings, enable S3-compatible access and create S3 access
keys.

Collect these values:

```bash
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@HOST:5432/postgres
SUSTENTRA_S3_ENDPOINT_URL=https://PROJECT_REF.supabase.co/storage/v1/s3
SUSTENTRA_S3_ACCESS_KEY_ID=...
SUSTENTRA_S3_SECRET_ACCESS_KEY=...
SUSTENTRA_S3_BUCKET=sustentra-documents
SUSTENTRA_S3_REGION=us-east-1
SUSTENTRA_S3_SECURE=true
```

If Supabase gives a pooled database URL, use the pooled host/port and keep the
`postgresql+psycopg2://` prefix for SQLAlchemy.

For Render, prefer the Supabase pooler connection string instead of the direct
`db.PROJECT_REF.supabase.co:5432` host. Some Supabase direct database hosts
resolve to IPv6, and Render free services may fail with `Network is
unreachable`. In Supabase, open **Project Settings -> Database -> Connection
string** and copy the **Transaction pooler** or **Session pooler** URI. Convert
the prefix for SQLAlchemy:

```bash
# Supabase gives:
postgresql://postgres.PROJECT_REF:PASSWORD@POOLER_HOST:6543/postgres

# Render should receive:
postgresql+psycopg2://postgres.PROJECT_REF:PASSWORD@POOLER_HOST:6543/postgres
```

## 2. Render Backend

Create a Render Blueprint from this repository. Render reads
`/render.yaml`, builds `/backend/Dockerfile`, runs migrations, and starts the
FastAPI backend.

Set these secret environment variables in Render:

```bash
DATABASE_URL=...
SUSTENTRA_S3_ENDPOINT_URL=https://PROJECT_REF.supabase.co/storage/v1/s3
SUSTENTRA_S3_ACCESS_KEY_ID=...
SUSTENTRA_S3_SECRET_ACCESS_KEY=...
OPENAI_API_KEY=...
SUSTENTRA_CORS_ORIGINS=https://YOUR_VERCEL_APP.vercel.app
```

Confirm the backend health URL after deploy:

```text
https://YOUR_RENDER_SERVICE.onrender.com/health
```

Expected response:

```json
{"status":"ok"}
```

## 3. Vercel Frontend

Import the same GitHub repository into Vercel as a monorepo project.

Set:

```text
Root Directory: frontend
Build Command: npm run build
Install Command: npm install
Output Directory: .next
```

Set Vercel environment variables:

```bash
NEXT_PUBLIC_BACKEND_API_URL=https://YOUR_RENDER_SERVICE.onrender.com
NEXT_PUBLIC_S1_DATA_MODE=backend
```

After Vercel gives you a frontend URL, add it back to Render:

```bash
SUSTENTRA_CORS_ORIGINS=https://YOUR_VERCEL_APP.vercel.app
```

Then redeploy the Render backend.

## 4. Smoke Test

1. Open the Vercel URL.
2. Upload a PDF.
3. Confirm processing completes.
4. Click the filename and confirm the PDF previews in the middle pane.
5. Upload a CSV.
6. Confirm the CSV previews as a table, not a browser download.
7. Accept or correct one field.
8. Refresh and confirm the review state persists.

## Notes

- Render free services sleep after inactivity, so first load can be slow.
- Supabase free has database and storage limits, but is enough for staging.
- Keep fixtures available locally; deployed staging should use backend mode.
