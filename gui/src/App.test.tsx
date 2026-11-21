// The page of a logged-in user: header, user menu, MaxMind attribution.
import { screen } from "@testing-library/react";

import { MAXMIND_URL } from "./components/Footer";
import { json, renderScreen, stubFetch } from "./test/render";

test("shows the name, the user and the MaxMind attribution", async () => {
  stubFetch((request) =>
    new URL(request.url).pathname === "/api/v1/health"
      ? json(200, { status: "ok", version: "0.1.0" })
      : json(200, []),
  );
  renderScreen("/");
  expect(screen.getByRole("heading", { name: "h42-mesh" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Account" })).toHaveTextContent("alice");
  expect(screen.getByText(/This product includes GeoLite2 data created by MaxMind/)).toBeInTheDocument();
  const link = screen.getByRole("link", { name: MAXMIND_URL });
  expect(link).toHaveAttribute("href", MAXMIND_URL);
  expect(await screen.findByText("Available (version 0.1.0)")).toBeInTheDocument();
});

test("an unknown address", async () => {
  stubFetch(() => json(200, []));
  renderScreen("/nowhere");
  expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
});
