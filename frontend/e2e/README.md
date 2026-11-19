# End-to-end smoke tests (TEST-002, TEST-008)

Two Playwright tests, run in this order by one worker.

**`smoke.spec.ts` (TEST-002)** walks the whole MVP account lifecycle through the
real UI, API, database and email:

1. a provider admin is seeded with the real CLI (`create-provider-admin --reset-link`),
2. sets a password from the printed link and signs in with password + emailed OTP,
3. creates an organization with an initial admin,
4. the admin opens the invite link from the email, sets a password, signs in with OTP,
5. and invites a member, who receives the invite email.

When it ends it saves the admin's signed-in session (`e2e/.admin-session.json`, git-ignored) for the next test.

**`workpaper.spec.ts` (TEST-008)** is the core path of the product, as that admin: create an engagement with one
facility, upload a fictional text-layer gas bill (`s1-test-suite/stationary_combustion/documents/SC-01`, read in
full by the rule readers: no Textract, no Claude), wait for "1 of 1 done" (the upload list's batch status is
polled by `expect`, never slept on), check the quantity card reads 1,284 therm = 128.4 MMBtu, **Accept** it, reload
and check it still reads accepted, accept the rest of the bill's values, and check Verification results shows the
natural gas line recomputed (about 6.8 tCO2e). It needs `smoke.spec.ts` to run first. Selectors are roles and
labels. It runs in about 5 seconds against the default `S1_STORE=jsonl` and inline processing.

Emails are read from Mailpit's API. Every run uses fresh emails and a fresh org slug,
so it can run repeatedly against the same database.

## Run it locally

```bash
docker compose up -d db mailpit api        # from the repo root
cd frontend
npm run build && npm start &               # or `npm run dev`
npx playwright install chromium            # once
npm run test:e2e
```

| Variable            | Default                                                                                                                                |                                           |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| `E2E_BASE_URL`      | `http://localhost:3000`                                                                                                                | the web app                               |
| `E2E_MAILPIT_URL`   | `http://localhost:8025`                                                                                                                | Mailpit UI/API                            |
| `E2E_SEED_COMMAND`  | `docker compose -f ../docker-compose.yml exec -T api python -m backend.app.cli create-provider-admin --email {email} ... --reset-link` | how to run the CLI; `{email}` is replaced |
| `E2E_CHROMIUM_PATH` | (unset)                                                                                                                                | use an already-installed Chromium         |

The HTML report is written to `playwright-report/` (open with `npx playwright show-report`).
In CI (`ci / e2e`) it is uploaded as an artifact when the test fails.
