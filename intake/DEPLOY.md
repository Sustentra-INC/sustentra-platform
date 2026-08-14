# Putting intake somewhere a person can test it

Written for someone non-technical. About 40 minutes end to end, most of it
waiting for things to build.

## What you are setting up, and why it is two things

The app has two halves:

| Half | What it does | Where it goes |
|---|---|---|
| **The screens** | What a client sees and clicks | **Vercel** — free |
| **The engine** | The questions, the rules, the answers | **Railway** — free trial, then about $5/month |

Vercel cannot host the engine: it runs Python and keeps files on a disk, and
Vercel does neither. Deploy only to Vercel and every screen loads and then
fails to fetch anything. That is the single most common way this goes wrong.

**Before you start, you need:**

- Your GitHub account, with the repository already pushed (it is)
- A free Vercel account
- A free Railway account
- An email account the app can send from — a Gmail **App Password** is easiest

---

## Step 1 — The engine, on Railway

1. Go to **railway.app** → **New Project** → **Deploy from GitHub repo**.
2. Choose `Sustentra-INC/sustentra-platform`.
3. Railway will try to guess how to build it. Point it at the recipe instead:
   open **Settings → Build**, set **Dockerfile Path** to `intake/Dockerfile`,
   and leave the root directory as the repository root. The build needs both
   `intake/` and `reference-data/`, so it must run from the top.
4. **Settings → Networking → Generate Domain.** Copy the address it gives you —
   something like `https://sustentra-intake-production.up.railway.app`. You need
   it in step 2.
5. **Add a disk**, or every restart erases the pilot. In **Settings → Volumes**,
   add one and set the mount path to `/data`.
6. **Variables** → paste these in, substituting your own values. Full list with
   explanations in `intake/.env.example`.

   ```
   INTAKE_DATA_DIR=/data
   INTAKE_ADMIN_API_KEY=<a long random string you invent>
   INTAKE_CORS_ALLOWED_ORIGINS=https://<your-vercel-address>
   INTAKE_VERIFY_URL_TEMPLATE=https://<your-vercel-address>/intake/login/verify?token={token}
   INTAKE_REVIEW_URL_TEMPLATE=https://<your-vercel-address>/intake/review/{escalation_id}
   INTAKE_EMAIL_ADAPTER=smtp
   INTAKE_EMAIL_FROM=<the address emails come from>
   INTAKE_SMTP_HOST=smtp.gmail.com
   INTAKE_SMTP_PORT=587
   INTAKE_SMTP_USERNAME=<your email address>
   INTAKE_SMTP_PASSWORD=<your Gmail App Password>
   ```

   You do not know the Vercel address yet. Put a placeholder now and come back
   in step 3 — this is the one bit of back-and-forth.

**Check it worked:** open `https://<your-railway-address>/v1/intake/health` in a
browser. You should see `{"status":"ok","surface":"intake"}`. If you see
anything else, the deploy logs on Railway will say why.

### About that Gmail App Password

A normal Gmail password will not work — Google blocks it. You need an **App
Password**: turn on 2-Step Verification on the Google account, then search
Google Account settings for "App passwords" and create one. It is a 16-character
string. Treat it like a password, because it is one.

---

## Step 2 — The screens, on Vercel

1. Go to **vercel.com** → **Add New → Project** → import the same repository.
2. **Set the Root Directory to `frontend`.** Vercel defaults to the top of the
   repository, where there is no website. This is the step people miss.
3. Under **Environment Variables**, add one:

   ```
   NEXT_PUBLIC_BACKEND_API_URL = https://<your-railway-address>
   ```

   No trailing slash. Without it the screens call your own laptop and nothing
   loads.
4. **Deploy.** Copy the address Vercel gives you.

---

## Step 3 — Introduce them to each other

Go back to Railway and replace the placeholder Vercel address in all three
variables (`INTAKE_CORS_ALLOWED_ORIGINS`, `INTAKE_VERIFY_URL_TEMPLATE`,
`INTAKE_REVIEW_URL_TEMPLATE`) with the real one. Railway restarts by itself.

Then redeploy on Vercel if you had to change its variable.

---

## Step 4 — Create your student a company

Clients cannot sign themselves up; you create the company, which is why there
is an admin key. Run this from any terminal, substituting your values:

```sh
curl -X POST https://<your-railway-address>/v1/intake/orgs \
  -H 'Content-Type: application/json' \
  -H 'X-Intake-Admin-Key: <the admin key you invented>' \
  -d '{
        "legal_name": "Test Studios",
        "owner_name": "Your Student",
        "owner_email": "student@university.edu",
        "created_by": "vivian@sustentra.com"
      }'
```

Send your student to `https://<your-vercel-address>/intake/login`. They enter
that email, get a link, and they are in.

### Give yourself a reviewer account too

So you can work the queue when they click "I'm not sure". Sign in as the client
first, then from that session add yourself. Or ask me and I will do it.

---

## Step 5 — Watch it happen

While your student works:

- `https://<your-vercel-address>/intake/review` — questions waiting on you
- `https://<your-vercel-address>/intake/review/metrics` — how long they took,
  where they got stuck

Both need a Sustentra reviewer account. Your student cannot see either; the
server refuses, not just the menu.

---

## Things worth knowing before you send the link

**Use a made-up company.** The sign-in is pilot-grade: no rate limiting, no
lockout. That is a documented limitation, not an oversight. Fine for a student
with fictional data; not yet right for a real client's real inventory.

**Escalation emails need a nudge.** Urgent ones send themselves. The batched
digests and the 12-hour reminders come from a command that has to be run on a
schedule:

```sh
python intake/scripts/send_escalation_notices.py
```

Railway can run this for you on a schedule — add it as a **Cron** service using
the same repository. Or skip it for a short test and just watch the queue
screen; nothing depends on the emails.

**The disk is a single disk.** Answers are stored as append-only files, which is
safe for one running copy and not for several at once. Do not scale it up to
multiple instances. Past a handful of clients this wants a real database, and
only the storage layer would change.

**Costs.** Vercel free. Railway free for the trial, then about $5/month for a
small instance and disk. Nothing else costs anything — the AI that reads typed
answers is off unless you switch it on.

---

## If something breaks

| What you see | What it means |
|---|---|
| Screens load, everything says "Failed to fetch" | `NEXT_PUBLIC_BACKEND_API_URL` is wrong or missing on Vercel |
| Browser console mentions CORS | `INTAKE_CORS_ALLOWED_ORIGINS` does not exactly match your Vercel address |
| Sign-in link goes to localhost | `INTAKE_VERIFY_URL_TEMPLATE` still has the placeholder |
| No email ever arrives | Still on the `outbox` adapter, or the Gmail App Password is wrong. Railway's logs will show the SMTP error |
| Everything resets after a restart | No volume mounted at `/data` |
| "Sign-in required" when creating a company | Wrong or missing `X-Intake-Admin-Key` |
