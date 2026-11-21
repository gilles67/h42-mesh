// The page of a logged-in user: header, user menu, MaxMind attribution.
import { screen } from "@testing-library/react";

import { App } from "./App";
import { UserContext } from "./auth/UserContext";
import { MAXMIND_URL } from "./components/Footer";
import { json, renderWithProviders, stubFetch } from "./test/render";
import { ALICE } from "./test/users";

test("shows the name, the user and the MaxMind attribution", async () => {
  stubFetch(() => json(200, { status: "ok", version: "0.1.0" }));
  renderWithProviders(
    <UserContext.Provider value={ALICE}>
      <App />
    </UserContext.Provider>,
  );
  expect(screen.getByRole("heading", { name: "h42-mesh" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Account" })).toHaveTextContent("alice");
  expect(screen.getByText(/This product includes GeoLite2 data created by MaxMind/)).toBeInTheDocument();
  const link = screen.getByRole("link", { name: MAXMIND_URL });
  expect(link).toHaveAttribute("href", MAXMIND_URL);
  expect(await screen.findByText("Available (version 0.1.0)")).toBeInTheDocument();
});
