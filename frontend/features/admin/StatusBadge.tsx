import styles from "./admin.module.css";

const CLASS: Record<string, string> = {
  active: styles.badgeActive,
  suspended: styles.badgeSuspended,
  invited: styles.badgeInvited,
  pending: styles.badgePending,
};

/** Small coloured status pill shared across the admin tables. */
export function StatusBadge({ status }: { status: string }) {
  return <span className={`${styles.badge} ${CLASS[status] ?? styles.badgePending}`}>{status}</span>;
}
