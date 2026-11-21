// Enrollment of a router: creates a single-use token and shows it once, with
// the command to run on the router. The controller only keeps a digest of
// the token: once the window is closed, it cannot be shown again (a new one
// can be created; it replaces the previous unused one).
import { Alert, Button, CopyButton, Code, Group, Modal, Stack, Text } from "@mantine/core";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { $api } from "../api/client";
import type { EnrollmentToken, Router } from "../api/types";
import { DateTime, ErrorAlert } from "../components/common";

/** The controller is served at the same address as this page (Traefik). */
export function enrollCommand(token: string, controller = globalThis.location.origin): string {
  return `h42-mesh-agent enroll --controller ${controller} --token ${token}`;
}

export function EnrollmentButton({ router }: { router: Router }) {
  const { t } = useTranslation();
  const [created, setCreated] = useState<EnrollmentToken | null>(null);
  const create = $api.useMutation("post", "/api/v1/routers/{router_id}/enrollment-tokens", {
    onSuccess: setCreated,
  });

  function close() {
    setCreated(null); // forgotten: shown once only
    create.reset();
  }

  return (
    <>
      <Button
        variant="light"
        loading={create.isPending}
        onClick={() => create.mutate({ params: { path: { router_id: router.id } } })}
      >
        {t(router.enrolled ? "enrollment.renew" : "enrollment.create")}
      </Button>
      {create.isError && <ErrorAlert error={create.error} />}
      <Modal opened={created !== null} onClose={close} title={t("enrollment.title")} size="lg">
        {created !== null && (
          <Stack>
            <Alert color="yellow">{t("enrollment.once")}</Alert>
            <Text size="sm">{t("enrollment.command")}</Text>
            <Code block>{enrollCommand(created.token)}</Code>
            <Group justify="space-between">
              <Text size="sm">
                {t("enrollment.expires")} <DateTime value={created.expires_at} />
              </Text>
              <CopyButton value={enrollCommand(created.token)}>
                {({ copied, copy }) => (
                  <Button color={copied ? "teal" : undefined} onClick={copy}>
                    {t(copied ? "common.copied" : "enrollment.copy")}
                  </Button>
                )}
              </CopyButton>
            </Group>
            <Text size="sm" c="dimmed">
              {t("enrollment.vrfHint")}
            </Text>
            <Button variant="default" onClick={close}>
              {t("common.close")}
            </Button>
          </Stack>
        )}
      </Modal>
    </>
  );
}
