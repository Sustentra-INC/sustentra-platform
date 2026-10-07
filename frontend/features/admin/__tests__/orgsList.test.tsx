/* @vitest-environment jsdom */
import { beforeEach, describe, expect, it, vi } from "vitest";
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("../providerApi", async () => {
  const actual = await vi.importActual<typeof import("../providerApi")>("../providerApi");
  return { ...actual, listOrgs: vi.fn() };
});

import { listOrgs } from "../providerApi";
import { OrgsList } from "../OrgsList";

const listMock = listOrgs as unknown as ReturnType<typeof vi.fn>;

const org = (n: number) => ({
  id: `o${n}`,
  name: `Org ${n}`,
  slug: `org-${n}`,
  status: "active" as const,
  max_users: 25,
  user_count: 1,
});

beforeEach(() => vi.clearAllMocks());

describe("OrgsList (FE-004)", () => {
  it("pages through the list and goes back to page 1 when the filter changes", async () => {
    listMock.mockImplementation(async ({ page = 1 }: { page?: number }) => ({
      items: [org(page)],
      total: 45,
      page,
      page_size: 20,
    }));
    render(<OrgsList />);
    await waitFor(() => expect(screen.getByText("Org 1")).toBeInTheDocument());
    expect(screen.getByText("Page 1 of 3")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(screen.getByText("Org 2")).toBeInTheDocument());
    expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));

    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "suspended" } });
    await waitFor(() =>
      expect(listMock).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, status: "suspended" })),
    );
  });

  it("hides the pager when everything fits on one page", async () => {
    listMock.mockResolvedValue({ items: [org(1)], total: 1, page: 1, page_size: 20 });
    render(<OrgsList />);
    await waitFor(() => expect(screen.getByText("Org 1")).toBeInTheDocument());
    expect(screen.queryByRole("navigation", { name: "Pages" })).not.toBeInTheDocument();
  });
});
