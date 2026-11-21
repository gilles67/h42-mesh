// Screen of one site: its details and its routers (number, name, state, last
// contact). With the "manage" access of its mesh: modify or delete the site,
// declare, rename, delete routers.
import { Anchor, Group, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";

import { useCanManage, useRefreshData } from "../api/access";
import { $api, fetchClient, orThrow } from "../api/client";
import { DateTime, ErrorAlert, NavBreadcrumbs, PageLoader } from "../components/common";
import { ConfirmDelete } from "../components/ConfirmDelete";
import { ModalButton } from "../components/ModalButton";
import { Field } from "../components/Field";
import { RouterForm } from "../inventory/RouterForm";
import { RouterStatus } from "../inventory/RouterStatus";
import { SiteForm } from "../inventory/SiteForm";

const MAX_ROUTERS = 2; // r0 and r1

export function SitePage() {
  const { t } = useTranslation();
  const { siteId = "" } = useParams();
  const navigate = useNavigate();
  const refresh = useRefreshData();
  const path = { params: { path: { site_id: siteId } } };
  const site = $api.useQuery("get", "/api/v1/sites/{site_id}", path);
  const routers = $api.useQuery("get", "/api/v1/sites/{site_id}/routers", path);
  const meshId = site.data?.mesh_id;
  const mesh = $api.useQuery(
    "get",
    "/api/v1/meshes/{mesh_id}",
    { params: { path: { mesh_id: meshId ?? "" } } },
    { enabled: meshId !== undefined },
  );
  const canManage = useCanManage(meshId);

  if (site.isPending) {
    return <PageLoader />;
  }
  if (site.isError) {
    return <ErrorAlert error={site.error} />;
  }
  const used = routers.data?.map((r) => r.number) ?? [];
  return (
    <Stack>
      <NavBreadcrumbs
        items={[
          { label: t("mesh.listTitle"), to: "/" },
          { label: mesh.data?.name ?? "…", to: `/meshes/${site.data.mesh_id}` },
          { label: site.data.nickname },
        ]}
      />
      <Group justify="space-between">
        <Title order={2}>
          {site.data.name} <Text span c="dimmed" ff="monospace">({site.data.nickname})</Text>
        </Title>
        {canManage && (
          <Group>
            <ModalButton
              label={t("common.edit")}
              title={t("site.edit", { nickname: site.data.nickname })}
              variant="default"
            >
              {(close) => <SiteForm meshId={site.data.mesh_id} site={site.data} onDone={close} />}
            </ModalButton>
            <ConfirmDelete
              label={t("site.delete")}
              message={t("site.deleteConfirm", { nickname: site.data.nickname })}
              onConfirm={() => orThrow(fetchClient.DELETE("/api/v1/sites/{site_id}", path))}
              onDeleted={() => {
                void refresh();
                void navigate(`/meshes/${site.data.mesh_id}`);
              }}
            />
          </Group>
        )}
      </Group>
      <SimpleGrid cols={{ base: 1, sm: 3 }}>
        <Field label={t("site.asn")}>
          <Text ff="monospace">{site.data.asn}</Text>
        </Field>
        <Field label={t("site.location")}>
          <Text>{site.data.location ?? "-"}</Text>
        </Field>
        <Field label={t("common.createdAt")}>
          <DateTime value={site.data.created_at} />
        </Field>
      </SimpleGrid>

      <Group justify="space-between">
        <Title order={3}>{t("router.listTitle")}</Title>
        {canManage && used.length < MAX_ROUTERS && (
          <ModalButton label={t("router.create")} title={t("router.create")}>
            {(close) => <RouterForm siteId={siteId} usedNumbers={used} onDone={close} />}
          </ModalButton>
        )}
      </Group>
      {routers.isPending && <PageLoader />}
      {routers.isError && <ErrorAlert error={routers.error} />}
      {routers.data?.length === 0 && <Text c="dimmed">{t("router.none")}</Text>}
      {routers.data !== undefined && routers.data.length > 0 && (
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("router.number")}</Table.Th>
              <Table.Th>{t("router.name")}</Table.Th>
              <Table.Th>{t("router.state")}</Table.Th>
              <Table.Th>{t("router.lastSeen")}</Table.Th>
              {canManage && <Table.Th />}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {routers.data.map((router) => (
              <Table.Tr key={router.id}>
                <Table.Td ff="monospace">{`r${router.number}`}</Table.Td>
                <Table.Td>
                  <Anchor component={Link} to={`/routers/${router.id}`}>
                    {router.name}
                  </Anchor>
                </Table.Td>
                <Table.Td>
                  <RouterStatus router={router} />
                </Table.Td>
                <Table.Td>
                  <DateTime value={router.last_seen_at} />
                </Table.Td>
                {canManage && (
                  <Table.Td>
                    <Group gap="xs" justify="flex-end">
                      <ModalButton
                        label={t("common.rename")}
                        title={t("router.rename")}
                        variant="default"
                        size="xs"
                      >
                        {(close) => <RouterForm siteId={siteId} router={router} onDone={close} />}
                      </ModalButton>
                      <ConfirmDelete
                        compact
                        label={t("common.delete")}
                        message={t("router.deleteConfirm", { name: router.name })}
                        onConfirm={() =>
                          orThrow(
                            fetchClient.DELETE("/api/v1/routers/{router_id}", {
                              params: { path: { router_id: router.id } },
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
