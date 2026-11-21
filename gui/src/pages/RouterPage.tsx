// Screen of one router: its state (enrollment, last contact, revocation) and
// its internet connections (role, priority, direct connections, ISP and
// public addresses found by the controller). With the "manage" access of its
// mesh: enrollment token, revocation, rename, deletion, and the connections.
import { Badge, Button, Group, SimpleGrid, Stack, Table, Text, Title } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router";

import { useCanManage, useRefreshData } from "../api/access";
import { $api, fetchClient, orThrow } from "../api/client";
import type { Connection } from "../api/types";
import { DateTime, ErrorAlert, NavBreadcrumbs, PageLoader } from "../components/common";
import { ConfirmDelete } from "../components/ConfirmDelete";
import { Field } from "../components/Field";
import { ModalButton } from "../components/ModalButton";
import { ConnectionForm } from "../inventory/ConnectionForm";
import { EnrollmentButton } from "../inventory/EnrollmentButton";
import { RouterForm } from "../inventory/RouterForm";
import { RouterStatus } from "../inventory/RouterStatus";

export function RouterPage() {
  const { t } = useTranslation();
  const { routerId = "" } = useParams();
  const navigate = useNavigate();
  const refresh = useRefreshData();
  const path = { params: { path: { router_id: routerId } } };
  const router = $api.useQuery("get", "/api/v1/routers/{router_id}", path);
  const connections = $api.useQuery("get", "/api/v1/routers/{router_id}/connections", path);
  const siteId = router.data?.site_id;
  const site = $api.useQuery(
    "get",
    "/api/v1/sites/{site_id}",
    { params: { path: { site_id: siteId ?? "" } } },
    { enabled: siteId !== undefined },
  );
  const meshId = site.data?.mesh_id;
  const mesh = $api.useQuery(
    "get",
    "/api/v1/meshes/{mesh_id}",
    { params: { path: { mesh_id: meshId ?? "" } } },
    { enabled: meshId !== undefined },
  );
  const canManage = useCanManage(meshId);
  const revoke = $api.useMutation("post", "/api/v1/routers/{router_id}/revoke", {
    onSuccess: () => refresh(),
  });

  if (router.isPending) {
    return <PageLoader />;
  }
  if (router.isError) {
    return <ErrorAlert error={router.error} />;
  }
  const data = router.data;
  const used = connections.data?.map((c) => c.number) ?? [];
  return (
    <Stack>
      <NavBreadcrumbs
        items={[
          { label: t("mesh.listTitle"), to: "/" },
          { label: mesh.data?.name ?? "…", to: meshId ? `/meshes/${meshId}` : "/" },
          { label: site.data?.nickname ?? "…", to: `/sites/${data.site_id}` },
          { label: `r${data.number}` },
        ]}
      />
      <Group justify="space-between">
        <Group>
          <Title order={2}>
            {data.name} <Text span c="dimmed" ff="monospace">{`r${data.number}`}</Text>
          </Title>
          <RouterStatus router={data} />
        </Group>
        {canManage && (
          <Group>
            <ModalButton label={t("common.rename")} title={t("router.rename")} variant="default">
              {(close) => <RouterForm siteId={data.site_id} router={data} onDone={close} />}
            </ModalButton>
            <ConfirmDelete
              label={t("router.delete")}
              message={t("router.deleteConfirm", { name: data.name })}
              onConfirm={() => orThrow(fetchClient.DELETE("/api/v1/routers/{router_id}", path))}
              onDeleted={() => {
                void refresh();
                void navigate(`/sites/${data.site_id}`);
              }}
            />
          </Group>
        )}
      </Group>

      <SimpleGrid cols={{ base: 1, sm: 4 }}>
        <Field label={t("router.enrolledAt")}>
          <DateTime value={data.enrolled_at} />
        </Field>
        <Field label={t("router.lastSeen")}>
          <DateTime value={data.last_seen_at} />
        </Field>
        <Field label={t("router.routesReportedAt")}>
          <DateTime value={data.routes_reported_at} />
        </Field>
        <Field label={t("common.createdAt")}>
          <DateTime value={data.created_at} />
        </Field>
      </SimpleGrid>

      {canManage && (
        <Stack gap="xs">
          <Title order={3}>{t("enrollment.sectionTitle")}</Title>
          <Text size="sm">{t(data.enrolled ? "enrollment.helpEnrolled" : "enrollment.help")}</Text>
          <Group>
            <EnrollmentButton router={data} />
            {data.enrolled && !data.signing_key_revoked && (
              <Button color="red" variant="light" loading={revoke.isPending} onClick={() => revoke.mutate(path)}>
                {t("router.revoke")}
              </Button>
            )}
          </Group>
          {revoke.isError && <ErrorAlert error={revoke.error} />}
        </Stack>
      )}

      <Group justify="space-between">
        <Title order={3}>{t("connection.listTitle")}</Title>
        {canManage && used.length < 10 && (
          <ModalButton label={t("connection.create")} title={t("connection.create")}>
            {(close) => <ConnectionForm routerId={routerId} usedNumbers={used} onDone={close} />}
          </ModalButton>
        )}
      </Group>
      {connections.isPending && <PageLoader />}
      {connections.isError && <ErrorAlert error={connections.error} />}
      {connections.data?.length === 0 && <Text c="dimmed">{t("connection.none")}</Text>}
      {connections.data !== undefined && connections.data.length > 0 && (
        <ConnectionTable connections={connections.data} canManage={canManage} routerId={routerId} />
      )}
    </Stack>
  );
}

type ConnectionTableProps = {
  connections: Connection[];
  canManage: boolean;
  routerId: string;
};

function ConnectionTable({ connections, canManage, routerId }: ConnectionTableProps) {
  const { t } = useTranslation();
  const refresh = useRefreshData();
  return (
    <Table striped>
      <Table.Thead>
        <Table.Tr>
          <Table.Th>{t("connection.number")}</Table.Th>
          <Table.Th>{t("connection.name")}</Table.Th>
          <Table.Th>{t("connection.role")}</Table.Th>
          <Table.Th>{t("connection.priority")}</Table.Th>
          <Table.Th>{t("connection.direct")}</Table.Th>
          <Table.Th>{t("connection.isp")}</Table.Th>
          <Table.Th>{t("connection.publicAddresses")}</Table.Th>
          {canManage && <Table.Th />}
        </Table.Tr>
      </Table.Thead>
      <Table.Tbody>
        {connections.map((connection) => (
          <Table.Tr key={connection.id}>
            <Table.Td ff="monospace">{`c${connection.number}`}</Table.Td>
            <Table.Td>
              <Text>{connection.name}</Text>
              {connection.description !== null && (
                <Text size="xs" c="dimmed">
                  {connection.description}
                </Text>
              )}
            </Table.Td>
            <Table.Td>
              <Badge variant="light" color={connection.role === "active" ? "teal" : "orange"}>
                {t(`values.role.${connection.role}`)}
              </Badge>
            </Table.Td>
            <Table.Td>{connection.priority ?? ""}</Table.Td>
            <Table.Td>{t(`values.direct.${connection.direct}`)}</Table.Td>
            <Table.Td>{connection.isp ?? ""}</Table.Td>
            <Table.Td ff="monospace">
              <Stack gap={0}>
                {connection.public_ipv4 !== null && <Text size="sm">{connection.public_ipv4}</Text>}
                {connection.public_ipv6 !== null && <Text size="sm">{connection.public_ipv6}</Text>}
                {connection.public_ipv4 === null && connection.public_ipv6 === null && (
                  <Text size="sm" c="dimmed">
                    {t("connection.notDiscovered")}
                  </Text>
                )}
              </Stack>
            </Table.Td>
            {canManage && (
              <Table.Td>
                <Group gap="xs" justify="flex-end" wrap="nowrap">
                  <ModalButton
                    label={t("common.edit")}
                    title={t("connection.edit", { number: connection.number })}
                    variant="default"
                    size="xs"
                  >
                    {(close) => (
                      <ConnectionForm routerId={routerId} connection={connection} onDone={close} />
                    )}
                  </ModalButton>
                  <ConfirmDelete
                    compact
                    label={t("common.delete")}
                    message={t("connection.deleteConfirm", { name: connection.name })}
                    onConfirm={() =>
                      orThrow(
                        fetchClient.DELETE("/api/v1/connections/{connection_id}", {
                          params: { path: { connection_id: connection.id } },
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
  );
}
