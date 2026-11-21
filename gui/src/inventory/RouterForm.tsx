// Declare a router (number r0 or r1, name) or rename one. The number cannot
// change afterwards: it is in the names of the tunnel interfaces.
import { Button, Select, Stack, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslation } from "react-i18next";

import { useRefreshData } from "../api/access";
import { $api } from "../api/client";
import type { Router } from "../api/types";
import { ErrorAlert } from "../components/common";

const ROUTER_NUMBERS = [0, 1];

type RouterFormProps = {
  siteId: string;
  /** Numbers already used in the site (only for a new router). */
  usedNumbers?: number[];
  /** The router to rename; none to declare one. */
  router?: Router;
  onDone: () => void;
};

export function RouterForm({ siteId, usedNumbers = [], router, onDone }: RouterFormProps) {
  const { t } = useTranslation();
  const refresh = useRefreshData();
  const free = ROUTER_NUMBERS.filter((n) => !usedNumbers.includes(n));
  const form = useForm({
    initialValues: { number: String(router?.number ?? free[0] ?? ""), name: router?.name ?? "" },
    validate: {
      number: (value) => (value !== "" ? null : t("validation.required")),
      name: (value) => (value.trim() ? null : t("validation.required")),
    },
  });
  const done = async () => {
    await refresh();
    onDone();
  };
  const create = $api.useMutation("post", "/api/v1/sites/{site_id}/routers", { onSuccess: done });
  const rename = $api.useMutation("patch", "/api/v1/routers/{router_id}", { onSuccess: done });
  const saving = router ? rename : create;

  function submit(values: { number: string; name: string }) {
    if (router) {
      rename.mutate({ params: { path: { router_id: router.id } }, body: { name: values.name.trim() } });
    } else {
      create.mutate({
        params: { path: { site_id: siteId } },
        body: { number: Number(values.number), name: values.name.trim() },
      });
    }
  }

  return (
    <form onSubmit={form.onSubmit(submit)}>
      <Stack>
        {!router && (
          <Select
            label={t("router.number")}
            description={t("router.numberHelp")}
            data={free.map((n) => ({ value: String(n), label: `r${n}` }))}
            allowDeselect={false}
            {...form.getInputProps("number")}
          />
        )}
        <TextInput label={t("router.name")} maxLength={64} data-autofocus {...form.getInputProps("name")} />
        {saving.isError && <ErrorAlert error={saving.error} />}
        <Button type="submit" loading={saving.isPending}>
          {t("common.save")}
        </Button>
      </Stack>
    </form>
  );
}
