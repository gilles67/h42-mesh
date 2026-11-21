// Screen of one mesh: its sites (nickname, name, AS, location). With the
// "manage" access: rename or delete the mesh, create, modify, delete sites.
import { Anchor, Badge, Group, Stack, Table, Text, Title } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { useCanManage, useRefreshData } from "../api/access";
import { $api, fetchClient, orThrow } from "../api/client";
import { ErrorAlert, NavBreadcrumbs, PageLoader } from "../components/common";
import { ConfirmDelete } from "../components/ConfirmDelete";
import { ModalButton } from "../components/ModalButton";
import { MeshForm } from "../inventory/MeshForm";
import { SiteForm } from "../inventory/SiteForm";

export function MeshPage() {
  const { t } = useTranslation();
  const { meshId = "" } = useParams();
  const navigate = useNavigate();
  const refresh = useRefreshData();
  const path = { params: { path: { mesh_id: meshId } } };
  const mesh = $api.useQuery("get", "/api/v1/meshes/{mesh_id}", path);
  const sites = $api.useQuery("get", "/api/v1/meshes/{mesh_id}/sites", path);
  const canManage = useCanManage(meshId);

  if (mesh.isPending) {
    return <PageLoader />;
  }
  if (mesh.isError) {
    return <ErrorAlert error={mesh.error} />;
  }
  return (
    <Stack>
      <NavBreadcrumbs items={[{ label: t("mesh.listTitle"), to: "/" }, { label: mesh.data.name }]} />
      <Group justify="space-between">
        <Group>
          <Title order={2}>{mesh.data.name}</Title>
          <Badge variant="light" color={canManage ? "teal" : "gray"}>
            {t(`values.access.${mesh.data.access_level}`)}
          </Badge>
        </Group>
        {canManage && (
          <Group>
            <ModalButton label={t("common.rename")} title={t("mesh.rename")} variant="default">
              {(close) => <MeshForm mesh={mesh.data} onDone={close} />}
            </ModalButton>
            <ConfirmDelete
              label={t("mesh.delete")}
              message={t("mesh.deleteConfirm", { name: mesh.data.name })}
              onConfirm={() =>
                orThrow(fetchClient.DELETE("/api/v1/meshes/{mesh_id}", path))
              }
              onDeleted={() => {
                void refresh();
                void navigate("/");
              }}
            />
          </Group>
        )}
      </Group>

      <Group justify="space-between">
        <Title order={3}>{t("site.listTitle")}</Title>
        {canManage && (
          <ModalButton label={t("site.create")} title={t("site.create")}>
            {(close) => <SiteForm meshId={meshId} onDone={close} />}
          </ModalButton>
        )}
      </Group>
      {sites.isPending && <PageLoader />}
      {sites.isError && <ErrorAlert error={sites.error} />}
      {sites.data?.length === 0 && <Text c="dimmed">{t("site.none")}</Text>}
      {sites.data !== undefined && sites.data.length > 0 && (
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("site.nickname")}</Table.Th>
              <Table.Th>{t("site.name")}</Table.Th>
              <Table.Th>{t("site.asn")}</Table.Th>
              <Table.Th>{t("site.location")}</Table.Th>
              {canManage && <Table.Th />}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {sites.data.map((site) => (
              <Table.Tr key={site.id}>
                <Table.Td>
                  <Anchor component={Link} to={`/sites/${site.id}`} ff="monospace">
                    {site.nickname}
                  </Anchor>
                </Table.Td>
                <Table.Td>{site.name}</Table.Td>
                <Table.Td ff="monospace">{site.asn}</Table.Td>
                <Table.Td>{site.location ?? ""}</Table.Td>
                {canManage && (
                  <Table.Td>
                    <Group gap="xs" justify="flex-end">
                      <ModalButton
                        label={t("common.edit")}
                        title={t("site.edit", { nickname: site.nickname })}
                        variant="default"
                        size="xs"
                      >
                        {(close) => <SiteForm meshId={meshId} site={site} onDone={close} />}
                      </ModalButton>
                      <ConfirmDelete
                        compact
                        label={t("common.delete")}
                        message={t("site.deleteConfirm", { nickname: site.nickname })}
                        onConfirm={() =>
                          orThrow(
                            fetchClient.DELETE("/api/v1/sites/{site_id}", {
                              params: { path: { site_id: site.id } },
                            }),
                          )
                        }
                        onDeleted={() => void refresh()}
                      />
                    </Group>
                  </Table.Td>
                )}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
