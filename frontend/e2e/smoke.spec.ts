import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

import { STATE_FILE } from "./global-setup";
import { waitForLink, waitForOtp } from "./mailpit";

/**
 * TEST-002 smoke: the whole MVP account lifecycle through the real UI, API, database
 * and email (Mailpit):
 *   provider seeded by CLI -> sets password -> logs in with OTP -> creates an org with
 *   an initial admin -> admin accepts the emailed invite -> logs in with OTP ->
 *   invites a member (who receives the email).
 */

const state = () =>
  JSON.parse(readFileSync(STATE_FILE, "utf8")) as {
    run: string;
    providerEmail: string;
    providerResetLink: string;
  };

const PASSWORD = "smoke-test-passphrase-2026";

async function signIn(page: Page, loginPath: string, email: string): Promise<void> {
  await page.goto(loginPath);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  const sentAfter = new Date();
  await page.getByRole("button", { name: "Sign in" }).click();
  const code = await waitForOtp(email, sentAfter);
  await page.getByLabel("6-digit code").fill(code); // submits itself at 6 digits
}

test("provider -> org -> invited admin -> member invite", async ({ page }) => {
  const { run, providerEmail, providerResetLink } = state();
  const slug = `smoke-${run}`;
  const adminEmail = `admin-${run}@smoke.test`;
  const memberEmail = `member-${run}@smoke.test`;

  await test.step("provider sets a password from the CLI link", async () => {
    await page.goto(providerResetLink);
    await page.getByLabel("New password").fill(PASSWORD);
    await page.getByLabel("Confirm password").fill(PASSWORD);
    await page.getByRole("button", { name: "Update password" }).click();
    await expect(page.getByRole("link", { name: /sign in/i })).toBeVisible();
  });

  await test.step("provider signs in with password + emailed OTP", async () => {
    await signIn(page, "/provider-admin/login", providerEmail);
    await expect(page).toHaveURL(/\/provider-admin\/orgs/);
  });

  const inviteSentAfter = new Date();
  await test.step("provider creates an org with an initial admin", async () => {
    await page.goto("/provider-admin/orgs/new");
    await page.getByLabel("Organization name").fill(`Smoke ${run}`);
    await page.getByLabel("Slug").fill(slug);
    await page.getByLabel("Seat limit").fill("5");
    await page.getByLabel("Admin email").fill(adminEmail);
    await page.getByLabel("First name").fill("Ada");
    await page.getByLabel("Last name").fill("Admin");
    await page.getByRole("button", { name: "Create organization" }).click();
    await expect(page).toHaveURL(/\/provider-admin\/orgs\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { name: `Smoke ${run}` })).toBeVisible();
  });

  await test.step("the admin accepts the emailed invite", async () => {
    const link = await waitForLink(adminEmail, inviteSentAfter, "/invite/accept");
    await page.context().clearCookies(); // a different person from here on
    await page.goto(link);
    await expect(page.getByText(`Join Smoke ${run}`)).toBeVisible();
    await expect(page.getByLabel("Email")).toHaveValue(adminEmail);
    await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
    await page.getByLabel("Confirm password").fill(PASSWORD);
    await page.getByRole("button", { name: "Activate account" }).click();
    await expect(page).toHaveURL(new RegExp(`/org/${slug}/login`));
  });

  await test.step("the admin signs in with password + emailed OTP", async () => {
    await signIn(page, `/org/${slug}/login`, adminEmail);
    await expect(page).not.toHaveURL(/\/login/);
  });

  await test.step("the admin invites a member, who gets the email", async () => {
    await page.goto(`/org/${slug}/admin/users/invite`);
    await page.getByLabel("Email").fill(memberEmail);
    await page.getByLabel("First name").fill("Max");
    await page.getByLabel("Last name").fill("Member");
    await page.getByLabel("Role").selectOption("org_member");
    const sentAfter = new Date();
    await page.getByRole("button", { name: "Send invite" }).click();
    await expect(page.getByText(`Invite sent to ${memberEmail}`)).toBeVisible();
    const link = await waitForLink(memberEmail, sentAfter, "/invite/accept");
    expect(link).toContain("/invite/accept?token=");

    await page.goto(`/org/${slug}/admin/users`);
    await expect(page.getByText(memberEmail)).toBeVisible();
    await expect(page.getByText("2 / 5 seats used")).toBeVisible();
  });
});
