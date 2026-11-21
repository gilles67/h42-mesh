// Menu of the logged-in user, in the header: change the password (in a
// window) and log out.
import { Button, Menu, Modal } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { useTranslation } from "react-i18next";

import { ChangePasswordForm } from "../auth/ChangePasswordForm";
import { useLogout } from "../auth/useLogout";
import { useUser } from "../auth/UserContext";

export function UserMenu() {
  const { t } = useTranslation();
  const user = useUser();
  const logout = useLogout();
  const [passwordOpen, password] = useDisclosure(false);
  return (
    <>
      <Menu position="bottom-end">
        <Menu.Target>
          <Button variant="default" aria-label={t("user.menu")}>
            {user.username}
          </Button>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item onClick={password.open}>{t("user.changePassword")}</Menu.Item>
          <Menu.Item color="red" onClick={() => logout.mutate()}>
            {t("common.logout")}
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>
      <Modal opened={passwordOpen} onClose={password.close} title={t("password.title")}>
        <ChangePasswordForm />
      </Modal>
    </>
  );
}
