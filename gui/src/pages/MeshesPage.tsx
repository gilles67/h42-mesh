// Screen "Meshes": the meshes the user can see, with their access level.
// Creating a mesh is offered to the administrator and to the users allowed to.
import { Anchor, Badge, Group, Stack, Table, Text, Title } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { Link, useNavigate } from "react-router";

import { $api } from "../api/client";
import { useUser } from "../auth/UserContext";
import { DateTime, ErrorAlert, PageLoader } from "../components/common";
import { ModalButton } from "../components/ModalButton";
import { MeshForm } from "../inventory/MeshForm";

export function MeshesPage() {
  const { t } = useTranslation();
  const user = useUser();
  const navigate = useNavigate();
  const meshes = $api.useQuery("get", "/api/v1/meshes");
  const canCreate = user.is_admin || user.can_create_meshes;

  return (
    <Stack>
      <Group justify="space-between">
        <Title order={2}>{t("mesh.listTitle")}</Title>
        {canCreate && (
          <ModalButton label={t("mesh.create")} title={t("mesh.create")}>
            {(close) => (
              <MeshForm
                onDone={(mesh) => {
                  close();
                  void navigate(`/meshes/${mesh.id}`);
                }}
              />
            )}
          </ModalButton>
        )}
      </Group>
      {meshes.isPending && <PageLoader />}
      {meshes.isError && <ErrorAlert error={meshes.error} />}
      {meshes.data?.length === 0 && (
        <Text c="dimmed">{t(canCreate ? "mesh.noneYet" : "mesh.noneShared")}</Text>
      )}
      {meshes.data !== undefined && meshes.data.length > 0 && (
        <Table striped>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("mesh.name")}</Table.Th>
              <Table.Th>{t("mesh.access")}</Table.Th>
              <Table.Th>{t("common.createdAt")}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {meshes.data.map((mesh) => (
              <Table.Tr key={mesh.id}>
                <Table.Td>
                  <Anchor component={Link} to={`/meshes/${mesh.id}`}>
                    {mesh.name}
                  </Anchor>
                </Table.Td>
                <Table.Td>
                  <Badge variant="light" color={mesh.access_level === "manage" ? "teal" : "gray"}>
                    {t(`values.access.${mesh.access_level}`)}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  <DateTime value={mesh.created_at} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}
    </Stack>
  );
}
