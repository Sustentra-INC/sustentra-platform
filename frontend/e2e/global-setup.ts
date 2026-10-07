import { execSync } from "node:child_process";
import { writeFileSync } from "node:fs";
import path from "node:path";

/**
 * Seed a provider admin with the real CLI (ORG-000) and hand the one-time
 * set-password link to the test. A fresh email per run keeps the test repeatable
 * against the same database.
 *
 * E2E_SEED_COMMAND runs the CLI; "{email}" is replaced. Default: the compose api service.
 */
export const RUN = Date.now().toString(36);
export const STATE_FILE = path.join(__dirname, ".state.json");

export default function globalSetup(): void {
  const email = `e2e-provider-${RUN}@sustentra.test`;
  const template =
    process.env.E2E_SEED_COMMAND ??
    "docker compose -f ../docker-compose.yml exec -T api python -m backend.app.cli create-provider-admin " +
      "--email {email} --first-name E2E --last-name Provider --reset-link";
  const output = execSync(template.replace("{email}", email), {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "inherit"],
  });
  const link = output.match(/https?:\/\/\S+reset-password\?token=\S+/)?.[0];
  if (!link) throw new Error(`create-provider-admin printed no set-password link:\n${output}`);
  writeFileSync(STATE_FILE, JSON.stringify({ run: RUN, providerEmail: email, providerResetLink: link }));
}
