// Screens Meshes, mesh (sites), site (routers) and router (connections,
// enrollment), against a fake controller. The modification buttons only
// appear with the "manage" access.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Mesh } from "../api/types";
import { fakeApi, json, renderScreen } from "../test/render";
import { FIBER, LTE, MESH, OTHER_MESH, ROUTER, SITE } from "../test/inventory";
import { ALICE } from "../test/users";

type User = ReturnType<typeof userEvent.setup>;

/** The fake controller, with the mesh in ``access`` level; ``extra`` adds routes. */
function controller(access: Mesh["access_level"] = "manage", extra = {}) {
  const mesh = { ...MESH, access_level: access };
  return fakeApi({
    "GET /api/v1/health": () => json(200, { status: "ok", version: "0.1.0" }),
    "GET /api/v1/meshes": () => json(200, [mesh, OTHER_MESH]),
    [`GET /api/v1/meshes/${MESH.id}`]: () => json(200, mesh),
    [`GET /api/v1/meshes/${MESH.id}/sites`]: () => json(200, [SITE]),
    [`GET /api/v1/sites/${SITE.id}`]: () => json(200, SITE),
    [`GET /api/v1/sites/${SITE.id}/routers`]: () => json(200, [ROUTER]),
    [`GET /api/v1/routers/${ROUTER.id}`]: () => json(200, ROUTER),
    [`GET /api/v1/routers/${ROUTER.id}/connections`]: () => json(200, [FIBER, LTE]),
    ...extra,
  });
}

/**
 * Choose ``option`` in the Mantine Select showing ``current`` (its label also
 * names the list of options, so the field is found by its value).
 */
async function choose(user: User, current: string, option: string) {
  await user.click(screen.getByDisplayValue(current));
  await user.click(await screen.findByRole("option", { name: option }));
}

const MODIFY = /^(Edit|Rename|Delete|New .*|Revoke|Create .*token)$/;

function modificationButtons() {
  return screen.queryAllByRole("button", { name: MODIFY });
}

// --- meshes ------------------------------------------------------------------

test("the meshes and the access to each", async () => {
  controller();
  renderScreen("/");
  const row = (await screen.findByRole("link", { name: "home42" })).closest("tr");
  expect(row).not.toBeNull();
  expect(within(row as HTMLElement).getByText("Manage")).toBeInTheDocument();
  expect(screen.getByText("Read only")).toBeInTheDocument();
  // Alice may not create meshes.
  expect(screen.queryByRole("button", { name: "New mesh" })).not.toBeInTheDocument();
});

test("create a mesh, then go to it", async () => {
  const user = userEvent.setup();
  const created = { ...MESH, id: "77777777-7777-4777-8777-777777777777", name: "lab" };
  const calls = controller("manage", {
    "POST /api/v1/meshes": () => json(201, created),
    [`GET /api/v1/meshes/${created.id}`]: () => json(200, created),
    [`GET /api/v1/meshes/${created.id}/sites`]: () => json(200, []),
  });
  renderScreen("/", { ...ALICE, can_create_meshes: true });
  await user.click(await screen.findByRole("button", { name: "New mesh" }));
  await user.type(screen.getByLabelText(/^Name/), "  lab ");
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("heading", { name: "lab" })).toBeInTheDocument();
  expect(screen.getByText("No site in this mesh yet.")).toBeInTheDocument();
  expect(calls.find((c) => c.method === "POST")?.body).toEqual({ name: "lab" });
});

// --- mesh and sites ----------------------------------------------------------

test("read-only mesh: the sites, without modification buttons", async () => {
  controller("read");
  renderScreen(`/meshes/${MESH.id}`);
  expect(await screen.findByRole("link", { name: "pari" })).toBeInTheDocument();
  expect(screen.getByText("4200000001")).toBeInTheDocument();
  expect(screen.getByText("Read only")).toBeInTheDocument();
  expect(modificationButtons()).toEqual([]);
});

test("create a site: checked, then sent", async () => {
  const user = userEvent.setup();
  const calls = controller("manage", {
    [`POST /api/v1/meshes/${MESH.id}/sites`]: () => json(201, { ...SITE, id: "x", nickname: "lyon" }),
  });
  renderScreen(`/meshes/${MESH.id}`);
  await user.click(await screen.findByRole("button", { name: "New site" }));
  await user.type(screen.getByLabelText(/^Name/), "Lyon");
  await user.type(screen.getByLabelText(/^Nickname/), "LYON");
  await user.type(screen.getByLabelText(/^AS number/), "65000");
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByText("4 characters: lower-case letters and digits only.")).toBeInTheDocument();
  expect(screen.getByText("A private AS from 4200000000 to 4294967294.")).toBeInTheDocument();

  await user.clear(screen.getByLabelText(/^Nickname/));
  await user.type(screen.getByLabelText(/^Nickname/), "lyon");
  await user.clear(screen.getByLabelText(/^AS number/));
  await user.type(screen.getByLabelText(/^AS number/), "4200000002");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() => expect(calls.some((c) => c.method === "POST")).toBe(true));
  const post = calls.find((c) => c.method === "POST");
  expect(post?.body).toEqual({ name: "Lyon", nickname: "lyon", asn: 4200000002, location: null });
  // The window closes once the site is created.
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

test("a refusal of the controller is translated", async () => {
  const user = userEvent.setup();
  controller("manage", {
    [`PATCH /api/v1/sites/${SITE.id}`]: () => json(409, { code: "nickname_taken", message: "x" }),
  });
  renderScreen(`/meshes/${MESH.id}`);
  await user.click(await screen.findByRole("button", { name: "Edit" }));
  expect(screen.getByLabelText(/^Location/)).toHaveValue("Paris, France");
  await user.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByText("A site of this mesh already has this nickname.")).toBeInTheDocument();
});

test("delete a site: confirmation, refusal shown", async () => {
  const user = userEvent.setup();
  controller("manage", {
    [`DELETE /api/v1/sites/${SITE.id}`]: () => json(409, { code: "site_not_empty", message: "x" }),
  });
  renderScreen(`/meshes/${MESH.id}`);
  await user.click(await screen.findByRole("button", { name: "Delete" }));
  expect(screen.getByText(/^Delete the site pari\?/)).toBeInTheDocument();
  const dialog = screen.getByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Delete" }));
  expect(await screen.findByText("The site still has routers: delete them first.")).toBeInTheDocument();
});

// --- site and routers --------------------------------------------------------

test("site: its routers and their state", async () => {
  const user = userEvent.setup();
  const calls = controller("manage", {
    [`POST /api/v1/sites/${SITE.id}/routers`]: () => json(201, { ...ROUTER, id: "y", number: 1 }),
  });
  renderScreen(`/sites/${SITE.id}`);
  expect(await screen.findByRole("link", { name: "gateway" })).toBeInTheDocument();
  expect(screen.getByText("Enrolled")).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: "home42" })).toHaveAttribute("href", `/meshes/${MESH.id}`);

  await user.click(screen.getByRole("button", { name: "New router" }));
  expect(screen.getByDisplayValue("r1")).toBeInTheDocument(); // r0 is taken
  await user.type(screen.getByLabelText(/^Name/), "backup gateway");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByRole("link", { name: "gateway" });
  expect(calls.find((c) => c.method === "POST")?.body).toEqual({ number: 1, name: "backup gateway" });
});

test("read-only site: no modification buttons", async () => {
  controller("read");
  renderScreen(`/sites/${SITE.id}`);
  expect(await screen.findByRole("link", { name: "gateway" })).toBeInTheDocument();
  expect(await screen.findByRole("link", { name: "home42" })).toBeInTheDocument();
  expect(modificationButtons()).toEqual([]);
});

// --- router, connections and enrollment --------------------------------------

test("router: its connections, values translated", async () => {
  controller("read");
  renderScreen(`/routers/${ROUTER.id}`);
  const fiber = (await screen.findByText("fiber")).closest("tr") as HTMLElement;
  expect(within(fiber).getByText("Active")).toBeInTheDocument();
  expect(within(fiber).getByText("IPv4 and IPv6")).toBeInTheDocument();
  expect(within(fiber).getByText("Orange")).toBeInTheDocument();
  expect(within(fiber).getByText("2a01:cb00::1")).toBeInTheDocument();
  const lte = screen.getByText("lte").closest("tr") as HTMLElement;
  expect(within(lte).getByText("Backup")).toBeInTheDocument();
  expect(within(lte).getByText("Not discovered yet")).toBeInTheDocument();
  // Read only: neither enrollment nor modification.
  expect(screen.queryByRole("heading", { name: "Enrollment" })).not.toBeInTheDocument();
  expect(modificationButtons()).toEqual([]);
});

test("declare a connection", async () => {
  const user = userEvent.setup();
  const calls = controller("manage", {
    [`POST /api/v1/routers/${ROUTER.id}/connections`]: () => json(201, { ...LTE, number: 2 }),
  });
  renderScreen(`/routers/${ROUTER.id}`);
  await user.click(await screen.findByRole("button", { name: "New connection" }));
  expect(screen.getByDisplayValue("c2")).toBeInTheDocument(); // c0, c1 taken
  await user.type(screen.getByLabelText(/^Name/), "starlink");
  await choose(user, "Active", "Backup");
  await choose(user, "None", "IPv6");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("fiber");
  expect(calls.find((c) => c.method === "POST")?.body).toEqual({
    number: 2,
    name: "starlink",
    role: "backup",
    priority: null,
    direct: "ipv6",
    description: null,
  });
});

test("modify a connection: emptied fields are cleared", async () => {
  const user = userEvent.setup();
  const calls = controller("manage", {
    [`PATCH /api/v1/connections/${FIBER.id}`]: () => json(200, FIBER),
  });
  renderScreen(`/routers/${ROUTER.id}`);
  const fiber = (await screen.findByText("fiber")).closest("tr") as HTMLElement;
  // The buttons appear once the access is known (router, then site, then mesh).
  await user.click(await within(fiber).findByRole("button", { name: "Edit" }));
  await user.clear(screen.getByLabelText(/^Priority/));
  await user.clear(screen.getByLabelText(/^Description/));
  await user.click(screen.getByRole("button", { name: "Save" }));
  await screen.findByText("fiber");
  expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
    name: "fiber",
    role: "active",
    priority: null,
    direct: "both",
    description: null,
  });
});

test("enrollment token: shown once, with the command to copy", async () => {
  const user = userEvent.setup();
  const token = "h42e_0123456789abcdefghijklmnopqrstuvwxyz";
  controller("manage", {
    [`POST /api/v1/routers/${ROUTER.id}/enrollment-tokens`]: () =>
      json(201, { token, expires_at: "2026-11-21T14:00:00Z" }),
  });
  renderScreen(`/routers/${ROUTER.id}`);
  await user.click(await screen.findByRole("button", { name: "Create a new enrollment token" }));
  const command = `h42-mesh-agent enroll --controller ${window.location.origin} --token ${token}`;
  expect(await screen.findByText(command)).toBeInTheDocument();
  expect(screen.getByText(/shown only once/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Copy the command" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Close" }));
  expect(screen.queryByText(command)).not.toBeInTheDocument();
  expect(screen.queryByText(new RegExp(token))).not.toBeInTheDocument();
});

test("revoke a router", async () => {
  const user = userEvent.setup();
  const calls = controller("manage", {
    [`POST /api/v1/routers/${ROUTER.id}/revoke`]: () =>
      json(200, { ...ROUTER, signing_key_revoked: true }),
  });
  renderScreen(`/routers/${ROUTER.id}`);
  await user.click(await screen.findByRole("button", { name: "Revoke" }));
  await screen.findByText("fiber");
  expect(calls.some((c) => c.path === `/api/v1/routers/${ROUTER.id}/revoke`)).toBe(true);
});

test("unknown mesh", async () => {
  fakeApi({
    "GET /api/v1/health": () => json(200, { status: "ok", version: "0.1.0" }),
    "GET /api/v1/meshes/00000000-0000-4000-8000-000000000000": () =>
      json(404, { code: "mesh_not_found", message: "No such mesh" }),
  });
  renderScreen("/meshes/00000000-0000-4000-8000-000000000000");
  expect(
    await screen.findByText("This mesh does not exist, or is not shared with you."),
  ).toBeInTheDocument();
});
