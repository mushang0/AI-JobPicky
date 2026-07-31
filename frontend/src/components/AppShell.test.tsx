import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppShell } from "./AppShell";

const { mockSignOut } = vi.hoisted(() => ({ mockSignOut: vi.fn().mockResolvedValue(undefined) }));

vi.mock("../adapters/web/AuthProvider", () => ({
  useAuth: () => ({
    status: "authenticated",
    user: { email: "demo@jobpicky.test" },
    signOut: mockSignOut,
  }),
}));

describe("AppShell", () => {
  afterEach(() => mockSignOut.mockClear());

  it("returns focus to the menu button when the mobile drawer closes with Escape", () => {
    render(
      <MemoryRouter initialEntries={["/jobs"]}>
        <AppShell />
      </MemoryRouter>,
    );

    const menuButton = screen.getByRole("button", { name: "打开导航" });
    fireEvent.click(menuButton);

    expect(menuButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "岗位池" })).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(menuButton).toHaveAttribute("aria-expanded", "false");
    expect(menuButton).toHaveFocus();
  });

  it("uses the authenticated account action to call logout", async () => {
    render(
      <MemoryRouter initialEntries={["/jobs"]}>
        <AppShell />
      </MemoryRouter>,
    );

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "退出登录 demo@jobpicky.test" }));
      await Promise.resolve();
    });

    expect(mockSignOut).toHaveBeenCalledOnce();
  });
});
