/**
 * R0-01/R1-06/R2-16/R3-04: a render-time throw anywhere in the app must
 * never replace the whole page with React Router's raw developer screen.
 * Drives a small router with the same nesting `routes.tsx` uses (see that
 * file's own comment on why the boundary sits one level under `AppShell`
 * rather than on its route directly) so this proves the shape actually
 * keeps the sidebar mounted, not just that the component renders in
 * isolation.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RouteErrorPage } from "@/components/RouteErrorPage";
import { AppShell } from "@/components/shell/AppShell";
import { RootLayout } from "@/components/shell/RootLayout";

function Boom(): never {
  throw new Error("kaboom from a test page");
}

function renderThrowingApp(initialPath: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      {
        element: <RootLayout />,
        errorElement: <RouteErrorPage standalone />,
        children: [
          {
            path: "/",
            element: <AppShell />,
            children: [
              {
                errorElement: <RouteErrorPage />,
                children: [
                  { index: true, element: <div>Live Map placeholder</div> },
                  { path: "aircraft", element: <Boom /> },
                ],
              },
            ],
          },
        ],
      },
    ],
    { initialEntries: [initialPath] },
  );
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("RouteErrorPage — in-chrome (nested under AppShell)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the fallback with the shell (sidebar) still present when a page throws", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    renderThrowingApp("/aircraft");

    // The whole point of nesting the boundary under AppShell rather than
    // putting it on the `/` route: the sidebar survives.
    expect(
      screen.getByRole("navigation", { name: /primary/i }),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", {
        name: /aircraft ran into a problem/i,
      }),
    ).toBeInTheDocument();
  });

  it("offers Try again and a link back to the Live Map", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    renderThrowingApp("/aircraft");

    expect(
      await screen.findByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /go to live map/i }),
    ).toHaveAttribute("href", "/");
  });

  it("logs the error to the console", async () => {
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => undefined);
    renderThrowingApp("/aircraft");

    await screen.findByRole("heading", {
      name: /aircraft ran into a problem/i,
    });
    expect(consoleError).toHaveBeenCalledWith(
      expect.stringContaining("Aircraft"),
      expect.any(Error),
    );
  });
});

describe("RouteErrorPage — standalone (chrome-free root fallback)", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders its own page frame with no shell when the boundary above AppShell fires", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);

    function BoomLayout(): never {
      throw new Error("kaboom from the layout itself");
    }

    const router = createMemoryRouter(
      [
        {
          path: "/",
          element: <BoomLayout />,
          errorElement: <RouteErrorPage standalone />,
        },
      ],
      { initialEntries: ["/"] },
    );
    render(<RouterProvider router={router} />);

    expect(
      screen.queryByRole("navigation", { name: /primary/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /live map ran into a problem/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /go to live map/i }),
    ).toBeInTheDocument();
  });
});
