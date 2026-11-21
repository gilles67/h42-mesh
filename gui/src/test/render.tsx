// Draws a component with its providers, and a fresh cache for each test.
import { QueryClient } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";

import { Providers } from "../Providers";

export function renderWithProviders(ui: ReactElement): RenderResult {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<Providers queryClient={queryClient}>{ui}</Providers>);
}

/** Replace fetch: every request gets this answer (or this error). */
export function stubFetch(answer: () => Promise<Response>): ReturnType<typeof vi.fn> {
  const fetch = vi.fn(answer);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

export function json(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}
