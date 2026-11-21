// Log out: POST /api/v1/auth/logout, then forget the user. Whatever the
// controller answers, the GUI goes back to the login screen.
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { fetchClient } from "../api/client";
import { forgetUser } from "./currentUser";

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await fetchClient.POST("/api/v1/auth/logout");
    },
    onSettled: () => {
      forgetUser(queryClient);
    },
  });
}
