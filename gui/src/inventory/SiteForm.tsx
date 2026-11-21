// Create or modify a site: name, nickname (4 characters), private AS and
// location. The checks here mirror the controller (SiteCreate), which checks
// again, as well as the uniqueness of the name, nickname and AS in the mesh.
import { Button, NumberInput, Stack, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslation } from "react-i18next";

import { useRefreshData } from "../api/access";
import { $api } from "../api/client";
import type { Site } from "../api/types";
import { ErrorAlert } from "../components/common";

export const ASN_MIN = 4_200_000_000;
export const ASN_MAX = 4_294_967_294;
const NICKNAME = /^[a-z0-9]{4}$/;

type SiteValues = { name: string; nickname: string; asn: number | string; location: string };

type SiteFormProps = {
  meshId: string;
  /** The site to modify; none to create one. */
  site?: Site;
  onDone: () => void;
};

export function SiteForm({ meshId, site, onDone }: SiteFormProps) {
  const { t } = useTranslation();
  const refresh = useRefreshData();
  const form = useForm<SiteValues>({
    initialValues: {
      name: site?.name ?? "",
      nickname: site?.nickname ?? "",
      asn: site?.asn ?? "",
      location: site?.location ?? "",
    },
    validate: {
      name: (value) => (value.trim() ? null : t("validation.required")),
      nickname: (value) => (NICKNAME.test(value) ? null : t("site.nicknameFormat")),
      asn: (value) =>
        typeof value === "number" && value >= ASN_MIN && value <= ASN_MAX
          ? null
          : t("site.asnRange", { min: ASN_MIN, max: ASN_MAX }),
    },
  });
  const done = async () => {
    await refresh();
    onDone();
  };
  const create = $api.useMutation("post", "/api/v1/meshes/{mesh_id}/sites", { onSuccess: done });
  const update = $api.useMutation("patch", "/api/v1/sites/{site_id}", { onSuccess: done });
  const saving = site ? update : create;

  function submit(values: SiteValues) {
    const body = {
      name: values.name.trim(),
      nickname: values.nickname,
      asn: Number(values.asn),
      location: values.location.trim() || null, // empty: no location
    };
    if (site) {
      update.mutate({ params: { path: { site_id: site.id } }, body });
    } else {
      create.mutate({ params: { path: { mesh_id: meshId } }, body });
    }
  }

  return (
    <form onSubmit={form.onSubmit(submit)}>
      <Stack>
        <TextInput label={t("site.name")} maxLength={64} data-autofocus {...form.getInputProps("name")} />
        <TextInput
          label={t("site.nickname")}
          description={t("site.nicknameHelp")}
          maxLength={4}
          {...form.getInputProps("nickname")}
        />
        <NumberInput
          label={t("site.asn")}
          description={t("site.asnHelp", { min: ASN_MIN, max: ASN_MAX })}
          min={ASN_MIN}
          max={ASN_MAX}
          allowDecimal={false}
          allowNegative={false}
          clampBehavior="none" // out of range: an error, not a silent change
          {...form.getInputProps("asn")}
        />
        <TextInput label={t("site.location")} maxLength={64} {...form.getInputProps("location")} />
        {saving.isError && <ErrorAlert error={saving.error} />}
        <Button type="submit" loading={saving.isPending}>
          {t("common.save")}
        </Button>
      </Stack>
    </form>
  );
}
