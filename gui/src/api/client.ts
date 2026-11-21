// Client of the controller API. The types come from schema.d.ts, generated
// from openapi/controller.json (npm run api:generate): paths, parameters and
// answers are checked by TypeScript. Never write API types by hand.
import createFetchClient from "openapi-fetch";
import createClient from "openapi-react-query";

import type { paths } from "./schema";

export const fetchClient = createFetchClient<paths>({
  // Same origin as the page: /api is served by the controller (Traefik in
  // production, the Vite proxy in development).
  baseUrl: globalThis.location?.origin ?? "",
  credentials: "include", // the session cookie
  // Looked up at each call, so that tests can replace fetch.
  fetch: (request: Request) => globalThis.fetch(request),
});

// Hooks for TanStack Query: $api.useQuery("get", "/api/v1/health").
export const $api = createClient(fetchClient);
