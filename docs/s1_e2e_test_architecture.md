# S1 End-to-End Test Architecture

S1 acceptance is split into three suites:

| Suite | Purpose | Default command |
|---|---|---|
| Fixture Contract E2E | Proves the July 30 build spec, Aug 10 revision, and Aug 12 addendum are represented in the frontend contract | `npm run e2e:s1:fixture` from `frontend/` |
| Local Real-Pipeline E2E | Proves local frontend -> backend -> persistence/storage -> extraction/review works without fixture mode | `S1_RUN_LOCAL_PIPELINE_E2E=1 npm run e2e:s1:local` |
| Cloud Real-Pipeline E2E | Proves deployed Vercel -> Render -> cloud persistence/storage behaves under real hosting conditions | `S1_CLOUD_URL=... S1_CLOUD_API_URL=... S1_RUN_CLOUD_E2E=1 npm run e2e:s1:cloud` |

The fixture suite is the PR gate because it covers frontend-only requirements and backend-blocked shapes. Local/cloud suites are capability-aware and should be enabled only when their backing stack and destructive controls are available.

## Required Environment

Fixture:

```bash
cd frontend
npm run e2e:s1:fixture
```

Local real stack:

```bash
docker compose up
cd frontend
S1_LOCAL_URL=http://127.0.0.1:3000 \
S1_LOCAL_API_URL=http://127.0.0.1:8000 \
S1_RUN_LOCAL_PIPELINE_E2E=1 \
npm run e2e:s1:local
```

Cloud real stack:

```bash
cd frontend
S1_CLOUD_URL=https://your-vercel-url.example \
S1_CLOUD_API_URL=https://your-render-url.example \
S1_RUN_CLOUD_E2E=1 \
npm run e2e:s1:cloud
```

## Gates

Gate 1, every PR:

```bash
npm test -- --run
npm run build
npm run e2e:s1:fixture
```

This is wired in `.github/workflows/s1-frontend-pr.yml`.

Gate 2, before deployment:

```bash
docker compose up
S1_RUN_LOCAL_PIPELINE_E2E=1 npm run e2e:s1:local
```

Gate 3, after Vercel/Render deployment:

```bash
S1_RUN_CLOUD_E2E=1 npm run e2e:s1:cloud
```

This is wired as a manual smoke gate in `.github/workflows/s1-cloud-smoke.yml`.
Connect it to Vercel/Render post-deploy automation when deployment credentials
and target URLs are available.

## Current Hook Coverage

The cloud suite includes explicit skipped hooks for Render cold start, Render restart persistence, and natural spin-down persistence. They require deployment-control environment variables because those operations should not run accidentally from a developer laptop or ordinary PR CI.

Until durable audit persistence exists, cloud audit tests must accept only one of two outcomes:

- durable audit entries survive reload/restart, or
- session-only entries disappear while the persistent non-retention notice clearly disclosed that behavior.

Silent disappearance without the notice is a failed S1 deployment.
