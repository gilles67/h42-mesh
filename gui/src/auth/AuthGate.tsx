// Decides what to show, from GET /api/v1/auth/me:
// - nobody logged in (or session expired): the login screen;
// - first login unfinished: password change, then TOTP setup;
// - otherwise: the application (children), with the user in UserContext.
// When any API call answers 401, the session has expired: the user is
// forgotten and the login screen comes back, with a message.
import { Alert, Button, Center, Loader } from "@mantine/core";
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { AuthLayout } from "./AuthLayout";
import { ChangePasswordPage } from "./ChangePasswordPage";
import { CURRENT_USER_KEY, forgetUser, useCurrentUser, type CurrentUser } from "./currentUser";
import { LoginPage } from "./LoginPage";
import { onSessionExpired } from "./session";
import { TotpSetupPage } from "./TotpSetupPage";
import { UserContext } from "./UserContext";

export function AuthGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const me = useCurrentUser();
  const [expired, setExpired] = useState(false);

  useEffect(
    () =>
      onSessionExpired(() => {
        const user = queryClient.getQueryData<CurrentUser | null>(CURRENT_USER_KEY);
        if (user) {
          // Someone was logged in: tell them why they are back here.
          setExpired(true);
          forgetUser(queryClient);
        }
      }),
    [queryClient],
  );

  const user = me.data;
  if (me.isPending) {
    return (
      <Center mih="100vh">
        <Loader />
      </Center>
    );
  }
  if (me.isError) {
    return (
      <AuthLayout title={t("auth.unreachableTitle")}>
        <Alert color="red">{t("errors.network")}</Alert>
        <Button onClick={() => void me.refetch()}>{t("common.retry")}</Button>
      </AuthLayout>
    );
  }
  if (!user) {
    return <LoginPage expired={expired} onLoggedIn={() => setExpired(false)} />;
  }
  switch (user.next_step) {
    case "change_password":
      return <ChangePasswordPage />;
    case "setup_totp":
      return <TotpSetupPage />;
    case "done":
      return <UserContext.Provider value={user}>{children}</UserContext.Provider>;
    default:
      // "totp": only possible for a session that is not complete.
      return <LoginPage expired={expired} onLoggedIn={() => setExpired(false)} />;
  }
}
