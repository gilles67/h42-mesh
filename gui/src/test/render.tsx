// Test helpers: draw a component with its providers (a fresh cache for each
// test), and replace the controller by a fake one answering from a table.
import { QueryClient } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";

import { Providers } from "../Providers";

export function renderWithProviders(ui: ReactElement): RenderResult {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <Providers queryClient={queryClient} env="test">
      {ui}
    </Providers>,
  );
}

type Answer = (request: Request) => Promise<Response>;

/** Replace fetch: every request gets this answer (or this error). */
export function stubFetch(answer: Answer): ReturnType<typeof vi.fn> {
  const fetch = vi.fn(answer);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

export function json(status: number, body?: unknown): Promise<Response> {
  if (body === undefined) {
    return Promise.resolve(new Response(null, { status }));
  }
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

export type ApiCall = { method: string; path: string; body: unknown };

/**
 * A fake controller. ``routes`` maps "METHOD /path" to an answer; the table
 * can be changed during the test. Unknown routes answer 404. Every request is
 * recorded in the returned list.
 */
export function fakeApi(routes: Record<string, Answer>): ApiCall[] {
  const calls: ApiCall[] = [];
  stubFetch(async (request) => {
    const path = new URL(request.url).pathname;
    const text = await request.clone().text();
    calls.push({ method: request.method, path, body: text ? JSON.parse(text) : undefined });
    const answer = routes[`${request.method} ${path}`];
    return answer ? answer(request) : json(404, { code: "not_found", message: path });
  });
  return calls;
}
