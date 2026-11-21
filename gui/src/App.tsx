// Page layout of the logged-in user: header (name, state of the controller,
// user menu), content, footer. Shown by the AuthGate once logged in.
import { AppShell, Group, Stack, Text, Title } from "@mantine/core";
import { useTranslation } from "react-i18next";

import { Footer } from "./components/Footer";
import { HealthStatus } from "./components/HealthStatus";
import { UserMenu } from "./components/UserMenu";

export function App() {
  const { t } = useTranslation();
  return (
    <AppShell header={{ height: 64 }} footer={{ height: 48 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Stack gap={0}>
            <Title order={3}>{t("app.title")}</Title>
            <Text size="xs" c="dimmed">
              {t("app.subtitle")}
            </Text>
          </Stack>
          <Group>
            <HealthStatus />
            <UserMenu />
          </Group>
        </Group>
      </AppShell.Header>
      <AppShell.Main>
        <Text>{t("app.welcome")}</Text>
      </AppShell.Main>
      <AppShell.Footer>
        <Footer />
      </AppShell.Footer>
    </AppShell>
  );
}
