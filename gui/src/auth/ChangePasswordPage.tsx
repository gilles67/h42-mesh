// First login, step 1: the password given at the creation of the account
// must be changed. The AuthGate shows this screen while next_step is
// "change_password".
import { Button, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";

import { AuthLayout } from "./AuthLayout";
import { ChangePasswordForm } from "./ChangePasswordForm";
import { useLogout } from "./useLogout";

export function ChangePasswordPage() {
  const { t } = useTranslation();
  const logout = useLogout();
  return (
    <AuthLayout title={t("password.title")}>
      <Text size="sm">{t("password.firstLogin")}</Text>
      <ChangePasswordForm />
      <Button variant="subtle" onClick={() => logout.mutate()}>
        {t("common.logout")}
      </Button>
    </AuthLayout>
  );
}
