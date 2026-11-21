// Small pieces shared by the screens: waiting, error, date, breadcrumbs.
import { Alert, Anchor, Breadcrumbs, Center, Loader, Text } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { errorKey } from "../api/errors";

export function PageLoader() {
  return (
    <Center py="xl">
      <Loader />
    </Center>
  );
}

/** An API error, translated from its code. */
export function ErrorAlert({ error }: { error: unknown }) {
  const { t } = useTranslation();
  return <Alert color="red">{t(errorKey(error))}</Alert>;
}

/** A date of the API (UTC), in the language and time zone of the browser. */
export function DateTime({ value }: { value: string | null }) {
  const { t, i18n } = useTranslation();
  if (value === null) {
    return <Text span c="dimmed">{t("common.never")}</Text>;
  }
  const formatted = new Intl.DateTimeFormat(i18n.language, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
  return <Text span>{formatted}</Text>;
}

export type Crumb = { label: string; to?: string };

/** Where we are: Meshes > mesh > site > router; each level is a link. */
export function NavBreadcrumbs({ items }: { items: Crumb[] }) {
  return (
    <Breadcrumbs>
      {items.map((item) =>
        item.to !== undefined ? (
          <Anchor key={item.to} component={Link} to={item.to}>
            {item.label}
          </Anchor>
        ) : (
          <Text key={item.label}>{item.label}</Text>
        ),
      )}
    </Breadcrumbs>
  );
}
