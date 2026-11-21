// Client of the controller API. The types come from schema.d.ts, generated
// from openapi/controller.json (npm run api:generate): paths, parameters and
// answers are checked by TypeScript. Never write API types by hand.
import createFetchClient from "openapi-fetch";
import createClient from "openapi-react-query";

import { notifySessionExpired } from "../auth/session";
import type { paths } from "./schema";

export const fetchClient = createFetchClient<paths>({
  // Same origin as the page: /api is served by the controller (Traefik in
  // production, the Vite proxy in development).
  baseUrl: globalThis.location?.origin ?? "",
  credentials: "include", // the session cookie
  // Looked up at each call, so that tests can replace fetch.
  fetch: (request: Request) => globalThis.fetch(request),
});

// The login steps answer 401 for a wrong password or code: not an expiry.
const LOGIN_STEPS = new Set(["/api/v1/auth/login", "/api/v1/auth/totp"]);

fetchClient.use({
  onResponse({ request, response }) {
    if (response.status === 401 && !LOGIN_STEPS.has(new URL(request.url).pathname)) {
      notifySessionExpired();
    }
    return undefined; // keep the response as it is
  },
});

// Hooks for TanStack Query: $api.useQuery("get", "/api/v1/health").
export const $api = createClient(fetchClient);

/**
 * Wait for a call of fetchClient and throw its error answer, if any: the
 * error then reaches TanStack Query like those of $api.useMutation.
 */
export async function orThrow(call: Promise<{ error?: unknown; response: Response }>): Promise<void> {
  const { error, response } = await call;
  if (!response.ok) {
    throw error ?? new Error(`HTTP ${response.status}`);
  }
}
