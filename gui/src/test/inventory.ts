// A small inventory answered by the fake controller in the tests:
// mesh "home42" > site "pari" > router r0 > connections c0 (fiber) and c1 (LTE).
import type { Connection, Mesh, Router, Site } from "../api/types";

export const MESH: Mesh = {
  id: "11111111-1111-4111-8111-111111111111",
  name: "home42",
  created_at: "2026-01-02T10:00:00Z",
  access_level: "manage",
};

export const OTHER_MESH: Mesh = {
  id: "22222222-2222-4222-8222-222222222222",
  name: "friends",
  created_at: "2026-02-03T10:00:00Z",
  access_level: "read",
};

export const SITE: Site = {
  id: "33333333-3333-4333-8333-333333333333",
  mesh_id: MESH.id,
  name: "Paris",
  nickname: "pari",
  location: "Paris, France",
  asn: 4200000001,
  created_at: "2026-01-02T11:00:00Z",
};

export const ROUTER: Router = {
  id: "44444444-4444-4444-8444-444444444444",
  site_id: SITE.id,
  number: 0,
  name: "gateway",
  enrolled: true,
  signing_key_revoked: false,
  enrolled_at: "2026-01-03T09:00:00Z",
  last_seen_at: "2026-11-21T08:00:00Z",
  routes_reported_at: null,
  created_at: "2026-01-02T12:00:00Z",
};

export const FIBER: Connection = {
  id: "55555555-5555-4555-8555-555555555555",
  router_id: ROUTER.id,
  number: 0,
  name: "fiber",
  role: "active",
  priority: 10,
  direct: "both",
  description: "Orange box in the garage",
  isp: "Orange",
  public_ipv4: "93.184.216.34",
  public_ipv4_updated_at: "2026-11-21T08:00:00Z",
  public_ipv6: "2a01:cb00::1",
  public_ipv6_updated_at: "2026-11-21T08:00:00Z",
  created_at: "2026-01-02T12:30:00Z",
};

export const LTE: Connection = {
  ...FIBER,
  id: "66666666-6666-4666-8666-666666666666",
  number: 1,
  name: "lte",
  role: "backup",
  priority: null,
  direct: "none",
  description: null,
  isp: null,
  public_ipv4: null,
  public_ipv4_updated_at: null,
  public_ipv6: null,
  public_ipv6_updated_at: null,
};
