// Page layout of the logged-in user: header (name, state of the controller,
// user menu), the screen of the current address, footer. Shown by the
// AuthGate once logged in.
//
// Addresses: /                  meshes
//            /meshes/:meshId    a mesh and its sites
//            /sites/:siteId     a site and its routers
//            /routers/:routerId a router, its connections and its enrollment
import { Anchor, AppShell, Group, Stack, Text, Title } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { Link, Route, Routes } from "react-router";

import { Footer } from "./components/Footer";
import { HealthStatus } from "./components/HealthStatus";
import { UserMenu } from "./components/UserMenu";
import { MeshesPage } from "./pages/MeshesPage";
import { MeshPage } from "./pages/MeshPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { RouterPage } from "./pages/RouterPage";
import { SitePage } from "./pages/SitePage";

export function App() {
  const { t } = useTranslation();
  return (
    <AppShell header={{ height: 64 }} footer={{ height: 48 }} padding="md">
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Stack gap={0}>
            <Anchor component={Link} to="/" underline="never" c="inherit">
              <Title order={3}>{t("app.title")}</Title>
            </Anchor>
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
        <Routes>
          <Route path="/" element={<MeshesPage />} />
          <Route path="/meshes/:meshId" element={<MeshPage />} />
          <Route path="/sites/:siteId" element={<SitePage />} />
          <Route path="/routers/:routerId" element={<RouterPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </AppShell.Main>
      <AppShell.Footer>
        <Footer />
      </AppShell.Footer>
    </AppShell>
  );
}
