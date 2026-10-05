/** Password policy hints shown on the reset page. The real policy (including the
 *  common-password check) is enforced server-side; the frontend only hints. */
export const PASSWORD_MIN_LENGTH = 12;

export const PASSWORD_HINTS: string[] = [
  `At least ${PASSWORD_MIN_LENGTH} characters`,
  "Not a common password",
];

/** Client-side checkable issues (length only; the server does the rest). */
export function passwordIssues(password: string): string[] {
  const issues: string[] = [];
  if (password.length < PASSWORD_MIN_LENGTH) {
    issues.push(`Use at least ${PASSWORD_MIN_LENGTH} characters`);
  }
  return issues;
}
