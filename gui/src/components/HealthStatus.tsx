// State of the controller (GET /api/v1/health, no authentication needed),
// checked again every 30 seconds. The first use of the generated client.
import { Badge, Group, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";

import { $api } from "../api/client";

const REFRESH_MS = 30_000;

/** The controller answered 503 with status "unavailable" (database down). */
function isUnavailable(error: unknown): boolean {
  return typeof error === "object" && error !== null && "status" in error && error.status === "unavailable";
}

export function HealthStatus() {
  const { t } = useTranslation();
  const { data, error, isPending } = $api.useQuery("get", "/api/v1/health", {}, {
    refetchInterval: REFRESH_MS,
    retry: false,
  });

  let badge;
  if (isPending) {
    badge = <Badge color="gray">{t("health.checking")}</Badge>;
  } else if (data !== undefined) {
    badge = <Badge color="green">{t("health.ok", { version: data.version })}</Badge>;
  } else {
    badge = (
      <Badge color="red">{t(isUnavailable(error) ? "health.unavailable" : "health.unreachable")}</Badge>
    );
  }
  return (
    <Group gap="xs">
      <Text size="sm">{t("health.label")}</Text>
      {badge}
    </Group>
  );
}
