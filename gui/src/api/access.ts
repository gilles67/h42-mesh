// Rights of the current user on a mesh, and refreshing the data after a change.
// Only the mesh carries the access level ("manage" or "read"); its sites,
// routers and connections share it. The controller checks the rights anyway:
// hiding the buttons only avoids offering what would be refused.
import { useQueryClient } from "@tanstack/react-query";

import { $api } from "./client";

export function useCanManage(meshId: string | undefined): boolean {
  const mesh = $api.useQuery(
    "get",
    "/api/v1/meshes/{mesh_id}",
    { params: { path: { mesh_id: meshId ?? "" } } },
    { enabled: meshId !== undefined },
  );
  return mesh.data?.access_level === "manage";
}

/** After a creation, change or deletion: read again what is displayed. */
export function useRefreshData(): () => Promise<void> {
  const queryClient = useQueryClient();
  // Every GET of the API client starts with "get" in its cache key.
  return () => queryClient.invalidateQueries({ queryKey: ["get"] });
}
