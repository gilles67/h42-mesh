// Declare or modify an internet connection: number (c0 to c9, fixed once
// created), name, role, priority, direct connections, description. The ISP
// and the public addresses are not typed in: the controller finds them.
import { Button, NumberInput, Select, Stack, Textarea, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslation } from "react-i18next";

import { useRefreshData } from "../api/access";
import { $api } from "../api/client";
import type { Connection, ConnectionRole, DirectMode } from "../api/types";
import { ErrorAlert } from "../components/common";

const CONNECTION_NUMBERS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
export const ROLES: ConnectionRole[] = ["active", "backup"];
export const DIRECT_MODES: DirectMode[] = ["none", "ipv4", "ipv6", "both"];
const PRIORITY_MAX = 1_000_000;

type ConnectionValues = {
  number: string;
  name: string;
  role: ConnectionRole;
  priority: number | string; // "" when empty
  direct: DirectMode;
  description: string;
};

type ConnectionFormProps = {
  routerId: string;
  /** Numbers already used on the router (only for a new connection). */
  usedNumbers?: number[];
  /** The connection to modify; none to declare one. */
  connection?: Connection;
  onDone: () => void;
};

export function ConnectionForm({ routerId, usedNumbers = [], connection, onDone }: ConnectionFormProps) {
  const { t } = useTranslation();
  const refresh = useRefreshData();
  const free = CONNECTION_NUMBERS.filter((n) => !usedNumbers.includes(n));
  const form = useForm<ConnectionValues>({
    initialValues: {
      number: String(connection?.number ?? free[0] ?? ""),
      name: connection?.name ?? "",
      role: connection?.role ?? "active",
      priority: connection?.priority ?? "",
      direct: connection?.direct ?? "none",
      description: connection?.description ?? "",
    },
    validate: {
      number: (value) => (value !== "" ? null : t("validation.required")),
      name: (value) => (value.trim() ? null : t("validation.required")),
    },
  });
  const done = async () => {
    await refresh();
    onDone();
  };
  const create = $api.useMutation("post", "/api/v1/routers/{router_id}/connections", {
    onSuccess: done,
  });
  const update = $api.useMutation("patch", "/api/v1/connections/{connection_id}", {
    onSuccess: done,
  });
  const saving = connection ? update : create;

  function submit(values: ConnectionValues) {
    const fields = {
      name: values.name.trim(),
      role: values.role,
      priority: typeof values.priority === "number" ? values.priority : null, // empty: none
      direct: values.direct,
      description: values.description.trim() || null,
    };
    if (connection) {
      update.mutate({ params: { path: { connection_id: connection.id } }, body: fields });
    } else {
      create.mutate({
        params: { path: { router_id: routerId } },
        body: { number: Number(values.number), ...fields },
      });
    }
  }

  return (
    <form onSubmit={form.onSubmit(submit)}>
      <Stack>
        {!connection && (
          <Select
            label={t("connection.number")}
            description={t("connection.numberHelp")}
            data={free.map((n) => ({ value: String(n), label: `c${n}` }))}
            allowDeselect={false}
            {...form.getInputProps("number")}
          />
        )}
        <TextInput label={t("connection.name")} maxLength={64} data-autofocus {...form.getInputProps("name")} />
        <Select
          label={t("connection.role")}
          description={t("connection.roleHelp")}
          data={ROLES.map((role) => ({ value: role, label: t(`values.role.${role}`) }))}
          allowDeselect={false}
          {...form.getInputProps("role")}
        />
        <NumberInput
          label={t("connection.priority")}
          description={t("connection.priorityHelp")}
          min={0}
          max={PRIORITY_MAX}
          allowDecimal={false}
          allowNegative={false}
          clampBehavior="none" // out of range: an error, not a silent change
          {...form.getInputProps("priority")}
        />
        <Select
          label={t("connection.direct")}
          description={t("connection.directHelp")}
          data={DIRECT_MODES.map((mode) => ({ value: mode, label: t(`values.direct.${mode}`) }))}
          allowDeselect={false}
          {...form.getInputProps("direct")}
        />
        <Textarea
          label={t("connection.description")}
          maxLength={2000}
          autosize
          minRows={2}
          {...form.getInputProps("description")}
        />
        {saving.isError && <ErrorAlert error={saving.error} />}
        <Button type="submit" loading={saving.isPending}>
          {t("common.save")}
        </Button>
      </Stack>
    </form>
  );
}
