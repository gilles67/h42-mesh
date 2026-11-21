// Who is logged in, according to GET /api/v1/auth/me. null when nobody is
// (no session, or expired). next_step says what the first login still needs.
import { useQuery, type QueryClient } from "@tanstack/react-query";

import { fetchClient } from "../api/client";
import type { components } from "../api/schema";

export type CurrentUser = components["schemas"]["CurrentUser"];

export const CURRENT_USER_KEY = ["auth", "me"] as const;

async function fetchCurrentUser(): Promise<CurrentUser | null> {
  const { data, response } = await fetchClient.GET("/api/v1/auth/me");
  if (response.status === 401) {
    return null;
  }
  if (data === undefined) {
    throw new Error(`GET /api/v1/auth/me: HTTP ${response.status}`);
  }
  return data;
}

export function useCurrentUser() {
  return useQuery({
    queryKey: CURRENT_USER_KEY,
    queryFn: fetchCurrentUser,
    retry: false,
    staleTime: 60_000,
  });
}

/** Ask the controller again (after a login step, a password change…). */
export function refreshCurrentUser(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: CURRENT_USER_KEY });
}

/** Nobody is logged in any more: forget the user and every data read for them. */
export function forgetUser(queryClient: QueryClient): void {
  queryClient.removeQueries({
    predicate: (query) =>
      query.queryKey[0] !== CURRENT_USER_KEY[0] && query.queryKey[1] !== "/api/v1/health",
  });
  queryClient.setQueryData(CURRENT_USER_KEY, null);
}
