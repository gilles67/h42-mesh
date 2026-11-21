// The whole page: header and MaxMind attribution in the footer.
import { screen } from "@testing-library/react";

import { App } from "./App";
import { MAXMIND_URL } from "./components/Footer";
import { json, renderWithProviders, stubFetch } from "./test/render";

test("shows the name and the MaxMind attribution", async () => {
  stubFetch(() => json(200, { status: "ok", version: "0.1.0" }));
  renderWithProviders(<App />);
  expect(screen.getByRole("heading", { name: "h42-mesh" })).toBeInTheDocument();
  expect(screen.getByText(/This product includes GeoLite2 data created by MaxMind/)).toBeInTheDocument();
  const link = screen.getByRole("link", { name: MAXMIND_URL });
  expect(link).toHaveAttribute("href", MAXMIND_URL);
  expect(await screen.findByText("Available (version 0.1.0)")).toBeInTheDocument();
});
