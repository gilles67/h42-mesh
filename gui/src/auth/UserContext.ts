// The logged-in user, given by the AuthGate to every component under it:
// useUser() reads it without asking the controller again.
import { createContext, useContext } from "react";

import type { CurrentUser } from "./currentUser";

export const UserContext = createContext<CurrentUser | null>(null);

export function useUser(): CurrentUser {
  const user = useContext(UserContext);
  if (user === null) {
    throw new Error("useUser() is only available inside the AuthGate");
  }
  return user;
}
