// State of the controller, with simulated answers (no controller needed).
import { screen } from "@testing-library/react";

import { json, renderWithProviders, stubFetch } from "../test/render";
import { HealthStatus } from "./HealthStatus";

test("available", async () => {
  const fetch = stubFetch(() => json(200, { status: "ok", version: "1.2.3" }));
  renderWithProviders(<HealthStatus />);
  expect(screen.getByText("Checking…")).toBeInTheDocument();
  expect(await screen.findByText("Available (version 1.2.3)")).toBeInTheDocument();
  const request = fetch.mock.calls[0]?.[0] as Request;
  expect(new URL(request.url).pathname).toBe("/api/v1/health");
  expect(request.credentials).toBe("include");
});

test("database unavailable (503)", async () => {
  stubFetch(() => json(503, { status: "unavailable", version: "1.2.3" }));
  renderWithProviders(<HealthStatus />);
  expect(await screen.findByText("Database unavailable")).toBeInTheDocument();
});

test("controller unreachable", async () => {
  stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));
  renderWithProviders(<HealthStatus />);
  expect(await screen.findByText("Unreachable")).toBeInTheDocument();
});
