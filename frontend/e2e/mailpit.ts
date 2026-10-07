/** Read the emails the API sent (Mailpit's REST API: https://mailpit.axllent.org/docs/api-v1/). */

const MAILPIT = process.env.E2E_MAILPIT_URL ?? "http://localhost:8025";

interface Summary {
  ID: string;
  Created: string;
  To: { Address: string }[];
  Subject: string;
}

/** Emails to `to` received after `after` (1 s of clock slack), newest first. */
async function emailsFor(to: string, after: Date): Promise<Summary[]> {
  const res = await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${to}"`)}&limit=20`);
  if (!res.ok) throw new Error(`Mailpit search failed: ${res.status}`);
  const body = (await res.json()) as { messages: Summary[] };
  return body.messages
    .filter((m) => new Date(m.Created).getTime() >= after.getTime() - 1000)
    .sort((a, b) => new Date(b.Created).getTime() - new Date(a.Created).getTime());
}

/**
 * Wait for an email to `to`, sent after `after`, whose plain-text body matches `pattern`,
 * and return the match. Emails that don't match (e.g. an earlier invite that falls inside
 * the clock slack while the OTP is still being sent) are skipped, not returned.
 */
async function waitForMatch(to: string, after: Date, pattern: RegExp, what: string, timeoutMs = 30_000): Promise<RegExpMatchArray> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const summary of await emailsFor(to, after)) {
      const res = await fetch(`${MAILPIT}/api/v1/message/${summary.ID}`);
      const message = (await res.json()) as { Text: string; HTML: string };
      const match = (message.Text || message.HTML).match(pattern);
      if (match) return match;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`No email with ${what} to ${to} within ${timeoutMs} ms`);
}

export async function waitForOtp(to: string, after: Date): Promise<string> {
  return (await waitForMatch(to, after, /\b(\d{6})\b/, "a 6-digit code"))[1];
}

export async function waitForLink(to: string, after: Date, path: string): Promise<string> {
  const pattern = new RegExp(`https?://\\S*${path.replace(/\//g, "\\/")}\\?token=[\\w%-]+`);
  return (await waitForMatch(to, after, pattern, `a ${path} link`))[0];
}
