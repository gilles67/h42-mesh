// Create a mesh, or rename one: a single field, its name.
import { Button, Stack, TextInput } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useTranslation } from "react-i18next";

import { useRefreshData } from "../api/access";
import { $api } from "../api/client";
import type { Mesh } from "../api/types";
import { ErrorAlert } from "../components/common";

type MeshFormProps = {
  /** The mesh to rename; none to create one. */
  mesh?: Mesh;
  onDone: (mesh: Mesh) => void;
};

export function MeshForm({ mesh, onDone }: MeshFormProps) {
  const { t } = useTranslation();
  const refresh = useRefreshData();
  const form = useForm({
    initialValues: { name: mesh?.name ?? "" },
    validate: { name: (value) => (value.trim() ? null : t("validation.required")) },
  });
  const done = async (saved: Mesh) => {
    await refresh();
    onDone(saved);
  };
  const create = $api.useMutation("post", "/api/v1/meshes", { onSuccess: done });
  const rename = $api.useMutation("patch", "/api/v1/meshes/{mesh_id}", { onSuccess: done });
  const saving = mesh ? rename : create;

  function submit(values: { name: string }) {
    const body = { name: values.name.trim() };
    if (mesh) {
      rename.mutate({ params: { path: { mesh_id: mesh.id } }, body });
    } else {
      create.mutate({ body });
    }
  }

  return (
    <form onSubmit={form.onSubmit(submit)}>
      <Stack>
        <TextInput label={t("mesh.name")} maxLength={64} data-autofocus {...form.getInputProps("name")} />
        {saving.isError && <ErrorAlert error={saving.error} />}
        <Button type="submit" loading={saving.isPending}>
          {t("common.save")}
        </Button>
      </Stack>
    </form>
  );
}
