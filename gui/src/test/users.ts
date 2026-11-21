// Users answered by the fake controller (GET /api/v1/auth/me) in the tests.
import type { CurrentUser } from "../auth/currentUser";

export const ALICE: CurrentUser = {
  id: "6f1c0d2e-8b7a-4c1e-9d3f-2a5b6c7d8e9f",
  username: "alice",
  is_admin: false,
  can_create_meshes: false,
  must_change_password: false,
  totp_enabled: true,
  next_step: "done",
};

export const FIRST_LOGIN: CurrentUser = {
  ...ALICE,
  must_change_password: true,
  totp_enabled: false,
  next_step: "change_password",
};

export const NO_TOTP_YET: CurrentUser = {
  ...FIRST_LOGIN,
  must_change_password: false,
  next_step: "setup_totp",
};
