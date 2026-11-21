// State of a router as a coloured badge: revoked, enrolled, or waiting for
// its enrollment.
import { Badge } from "@mantine/core";
import { useTranslation } from "react-i18next";

import type { Router } from "../api/types";

export function RouterStatus({ router }: { router: Router }) {
  const { t } = useTranslation();
  if (router.signing_key_revoked) {
    return <Badge color="red">{t("router.status.revoked")}</Badge>;
  }
  if (router.enrolled) {
    return <Badge color="green">{t("router.status.enrolled")}</Badge>;
  }
  return <Badge color="gray">{t("router.status.waiting")}</Badge>;
}
