import { fireEvent, screen, within } from "@testing-library/react";

/**
 * Picks one of a Methodology row's actions: from its "⋯" menu (Edit, Reject, Revert, Assign to…,
 * Mark for client follow-up, Remove row), or the "Add value" button a row with no value shows instead of Edit.
 */
export function rowAction(scope: HTMLElement, action: string, label: string) {
  const add = within(scope).queryByRole("button", { name: `Add value: ${label}` });
  if (action === "Edit" && add) return fireEvent.click(add);
  fireEvent.click(within(scope).getByRole("button", { name: `More actions: ${label}` }));
  fireEvent.click(screen.getByRole("menuitem", { name: action }));
}

/** The items a row's "⋯" menu offers, or [] when the row has no menu. The menu is closed again. */
export function menuItems(scope: HTMLElement, label: string): string[] {
  const trigger = within(scope).queryByRole("button", { name: `More actions: ${label}` });
  if (!trigger) return [];
  fireEvent.click(trigger);
  const names = screen.getAllByRole("menuitem").map((i) => i.textContent ?? "");
  fireEvent.keyDown(screen.getByRole("menu"), { key: "Escape" });
  return names;
}
