// Login, first login (password, TOTP with QR code), logout and session
// expiry, against a fake controller.
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { $api } from "../api/client";
import { App } from "../App";
import { fakeApi, json, renderWithProviders } from "../test/render";
import { ALICE, FIRST_LOGIN, NO_TOTP_YET } from "../test/users";
import { AuthGate } from "./AuthGate";
import type { CurrentUser } from "./currentUser";

const NOT_AUTHENTICATED = { code: "not_authenticated", message: "Authentication required" };
const SECRET = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP";

/** The fake controller; ``state.me`` is who GET /auth/me returns (null: 401). */
function controller(state: { me: CurrentUser | null }, extra = {}) {
  return fakeApi({
    "GET /api/v1/health": () => json(200, { status: "ok", version: "0.1.0" }),
    "GET /api/v1/auth/me": () => (state.me ? json(200, state.me) : json(401, NOT_AUTHENTICATED)),
    "POST /api/v1/auth/logout": () => {
      state.me = null;
      return json(204);
    },
    ...extra,
  });
}

function renderApp() {
  renderWithProviders(
    <AuthGate>
      <App />
    </AuthGate>,
  );
}

async function fillPassword(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText(/^Username/), "alice");
  await user.type(screen.getByLabelText(/^Password/), "correct horse");
  await user.click(screen.getByRole("button", { name: "Log in" }));
}

// --- login -------------------------------------------------------------------

test("nobody logged in: the login screen", async () => {
  controller({ me: null });
  renderApp();
  expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  expect(screen.queryByText(/session has expired/)).not.toBeInTheDocument();
});

test("password, then TOTP code, then the application", async () => {
  const user = userEvent.setup();
  const state = { me: null as CurrentUser | null };
  const calls = controller(state, {
    "POST /api/v1/auth/login": () => json(200, { next_step: "totp" }),
    "POST /api/v1/auth/totp": () => {
      state.me = ALICE;
      return json(200, { next_step: "done" });
    },
  });
  renderApp();
  await fillPassword(user);
  expect(await screen.findByRole("heading", { name: "Two-factor authentication" })).toBeInTheDocument();
  await user.type(screen.getByLabelText(/^Code/), "123456");
  await user.click(screen.getByRole("button", { name: "Verify" }));
  expect(await screen.findByRole("button", { name: "Account" })).toHaveTextContent("alice");
  expect(calls.filter((c) => c.method === "POST").map((c) => [c.path, c.body])).toEqual([
    ["/api/v1/auth/login", { username: "alice", password: "correct horse" }],
    ["/api/v1/auth/totp", { code: "123456" }],
  ]);
});

test.each([
  [401, "invalid_credentials", "Invalid username or password."],
  [429, "account_locked", "Too many failed attempts. Try again later."],
])("login refused (%i %s)", async (status, code, message) => {
  const user = userEvent.setup();
  controller({ me: null }, { "POST /api/v1/auth/login": () => json(status, { code, message: "x" }) });
  renderApp();
  await fillPassword(user);
  expect(await screen.findByText(message)).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Log in" })).toBeInTheDocument();
});

test("a TOTP code has 6 digits", async () => {
  const user = userEvent.setup();
  const calls = controller({ me: null }, {
    "POST /api/v1/auth/login": () => json(200, { next_step: "totp" }),
  });
  renderApp();
  await fillPassword(user);
  await user.type(await screen.findByLabelText(/^Code/), "12a3");
  expect(screen.getByLabelText(/^Code/)).toHaveValue("123"); // digits only
  await user.click(screen.getByRole("button", { name: "Verify" }));
  expect(screen.getByText("Enter the 6 digits of the code.")).toBeInTheDocument();
  expect(calls.some((c) => c.path === "/api/v1/auth/totp")).toBe(false);
});

test("wrong TOTP code", async () => {
  const user = userEvent.setup();
  controller({ me: null }, {
    "POST /api/v1/auth/login": () => json(200, { next_step: "totp" }),
    "POST /api/v1/auth/totp": () => json(401, { code: "invalid_totp_code", message: "x" }),
  });
  renderApp();
  await fillPassword(user);
  await user.type(await screen.findByLabelText(/^Code/), "000000");
  await user.click(screen.getByRole("button", { name: "Verify" }));
  expect(await screen.findByText(/^Invalid code/)).toBeInTheDocument();
});

// --- first login -------------------------------------------------------------

test("first login: new password, then TOTP with its QR code", async () => {
  const user = userEvent.setup();
  const state = { me: FIRST_LOGIN as CurrentUser | null };
  const calls = controller(state, {
    "POST /api/v1/auth/password": () => {
      state.me = NO_TOTP_YET;
      return json(204);
    },
    "POST /api/v1/auth/totp/setup": () =>
      json(200, {
        secret: SECRET,
        otpauth_uri: `otpauth://totp/h42-mesh:alice?secret=${SECRET}&issuer=h42-mesh`,
      }),
    "POST /api/v1/auth/totp/confirm": () => {
      state.me = ALICE;
      return json(204);
    },
  });
  renderApp();

  // Password: checked before sending.
  expect(await screen.findByRole("heading", { name: "Change your password" })).toBeInTheDocument();
  await user.type(screen.getByLabelText(/^Current password/), "initial password");
  await user.type(screen.getByLabelText(/^New password/), "short");
  await user.type(screen.getByLabelText(/^Confirm the new password/), "short");
  await user.click(screen.getByRole("button", { name: "Change the password" }));
  expect(screen.getByText("The new password must have at least 12 characters.")).toBeInTheDocument();
  await user.clear(screen.getByLabelText(/^New password/));
  await user.type(screen.getByLabelText(/^New password/), "a long new password");
  await user.click(screen.getByRole("button", { name: "Change the password" }));
  expect(screen.getByText("The two new passwords differ.")).toBeInTheDocument();
  await user.clear(screen.getByLabelText(/^Confirm the new password/));
  await user.type(screen.getByLabelText(/^Confirm the new password/), "a long new password");
  await user.click(screen.getByRole("button", { name: "Change the password" }));

  // TOTP: QR code, key to type by hand, first code.
  expect(
    await screen.findByRole("heading", { name: "Set up two-factor authentication" }),
  ).toBeInTheDocument();
  expect(await screen.findByTitle("QR code for the authenticator app")).toBeInTheDocument();
  expect(screen.getByText("JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP")).toBeInTheDocument();
  await user.type(screen.getByLabelText(/^Code/), "654321");
  await user.click(screen.getByRole("button", { name: "Enable" }));

  expect(await screen.findByRole("button", { name: "Account" })).toBeInTheDocument();
  const posts = calls.filter((c) => c.method === "POST").map((c) => [c.path, c.body]);
  expect(posts).toEqual([
    ["/api/v1/auth/password", { current_password: "initial password", new_password: "a long new password" }],
    ["/api/v1/auth/totp/setup", undefined],
    ["/api/v1/auth/totp/confirm", { secret: SECRET, code: "654321" }],
  ]);
});

test("first login: wrong current password", async () => {
  const user = userEvent.setup();
  controller({ me: FIRST_LOGIN }, {
    "POST /api/v1/auth/password": () => json(400, { code: "invalid_password", message: "x" }),
  });
  renderApp();
  await user.type(await screen.findByLabelText(/^Current password/), "wrong password");
  await user.type(screen.getByLabelText(/^New password/), "a long new password");
  await user.type(screen.getByLabelText(/^Confirm the new password/), "a long new password");
  await user.click(screen.getByRole("button", { name: "Change the password" }));
  expect(await screen.findByText("Wrong current password.")).toBeInTheDocument();
});

// --- logout, password change, expiry -----------------------------------------

test("log out", async () => {
  const user = userEvent.setup();
  const calls = controller({ me: ALICE });
  renderApp();
  await user.click(await screen.findByRole("button", { name: "Account" }));
  await user.click(await screen.findByRole("menuitem", { name: "Log out" }));
  expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  expect(screen.queryByText(/session has expired/)).not.toBeInTheDocument();
  expect(calls.some((c) => c.path === "/api/v1/auth/logout")).toBe(true);
});

test("change the password from the user menu", async () => {
  const user = userEvent.setup();
  const calls = controller({ me: ALICE }, { "POST /api/v1/auth/password": () => json(204) });
  renderApp();
  await user.click(await screen.findByRole("button", { name: "Account" }));
  await user.click(await screen.findByRole("menuitem", { name: "Change password" }));
  await user.type(await screen.findByLabelText(/^Current password/), "a long old password");
  await user.type(screen.getByLabelText(/^New password/), "a long new password");
  await user.type(screen.getByLabelText(/^Confirm the new password/), "a long new password");
  await user.click(screen.getByRole("button", { name: "Change the password" }));
  expect(await screen.findByText(/^Password changed/)).toBeInTheDocument();
  expect(calls.some((c) => c.path === "/api/v1/auth/password")).toBe(true);
});

function MeshesProbe() {
  // Any call that needs a session: here the list of meshes.
  const meshes = $api.useQuery("get", "/api/v1/meshes");
  return <p>{meshes.isPending ? "loading" : "loaded"}</p>;
}

test("session expired: back to the login screen, with a message", async () => {
  const state = { me: ALICE as CurrentUser | null };
  controller(state, {
    "GET /api/v1/meshes": () => {
      state.me = null; // the controller forgot the session
      return json(401, NOT_AUTHENTICATED);
    },
  });
  renderWithProviders(
    <AuthGate>
      <MeshesProbe />
    </AuthGate>,
  );
  expect(await screen.findByRole("heading", { name: "Log in" })).toBeInTheDocument();
  expect(screen.getByText("Your session has expired. Please log in again.")).toBeInTheDocument();
});

test("controller unreachable", async () => {
  const user = userEvent.setup();
  let reachable = false;
  controller({ me: ALICE }, {
    "GET /api/v1/auth/me": () =>
      reachable ? json(200, ALICE) : Promise.reject(new TypeError("Failed to fetch")),
  });
  renderApp();
  expect(await screen.findByRole("heading", { name: "Controller unreachable" })).toBeInTheDocument();
  reachable = true;
  await user.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByRole("button", { name: "Account" })).toBeInTheDocument();
});
