// Page layout: header (name, state of the controller), content, footer.
import { AppShell, Group, Stack, Text, Title } from "@mantine/core";
import { useTranslation } from "react-i18next";

import { Footer } from "./components/Footer";
import { HealthStatus } from "./components/HealthStatus";

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
          <HealthStatus />
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
