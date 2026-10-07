/** Read the emails the API sent (Mailpit's REST API: https://mailpit.axllent.org/docs/api-v1/). */

const MAILPIT = process.env.E2E_MAILPIT_URL ?? "http://localhost:8025";

interface Summary {
  ID: string;
  Created: string;
  To: { Address: string }[];
  Subject: string;
}

async function latestFor(to: string, after: Date): Promise<Summary | undefined> {
  const res = await fetch(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${to}"`)}&limit=20`);
  if (!res.ok) throw new Error(`Mailpit search failed: ${res.status}`);
  const body = (await res.json()) as { messages: Summary[] };
  return body.messages
    .filter((m) => new Date(m.Created).getTime() >= after.getTime() - 1000)
    .sort((a, b) => new Date(b.Created).getTime() - new Date(a.Created).getTime())[0];
}

/** Wait for the newest email to `to` sent after `after`, and return its plain-text body. */
export async function waitForEmail(to: string, after: Date, timeoutMs = 30_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const found = await latestFor(to, after);
    if (found) {
      const res = await fetch(`${MAILPIT}/api/v1/message/${found.ID}`);
      const message = (await res.json()) as { Text: string; HTML: string };
      return message.Text || message.HTML;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`No email to ${to} within ${timeoutMs} ms`);
}

export async function waitForOtp(to: string, after: Date): Promise<string> {
  const text = await waitForEmail(to, after);
  const match = text.match(/\b(\d{6})\b/);
  if (!match) throw new Error(`No 6-digit code in the email to ${to}`);
  return match[1];
}

export async function waitForLink(to: string, after: Date, path: string): Promise<string> {
  const text = await waitForEmail(to, after);
  const match = text.match(new RegExp(`https?://\\S*${path.replace(/\//g, "\\/")}\\?token=[\\w%-]+`));
  if (!match) throw new Error(`No ${path} link in the email to ${to}`);
  return match[0];
}
