// Frame of the screens shown before the application: login, first-login
// password change and TOTP setup. A centred card, with the controller state.
import { Center, Group, Paper, Stack, Title } from "@mantine/core";
import type { ReactNode } from "react";

import { HealthStatus } from "../components/HealthStatus";

type AuthLayoutProps = {
  title: string;
  children: ReactNode;
};

export function AuthLayout({ title, children }: AuthLayoutProps) {
  return (
    <Center mih="100vh" p="md">
      <Stack w="100%" maw={420}>
        <Paper withBorder shadow="sm" p="xl">
          <Stack>
            <Title order={2}>{title}</Title>
            {children}
          </Stack>
        </Paper>
        <Group justify="center">
          <HealthStatus />
        </Group>
      </Stack>
    </Center>
  );
}
