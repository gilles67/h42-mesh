// API errors turned into translation keys.
import { groupSecret } from "../auth/TotpSetupPage";
import { errorKey } from "./errors";

test.each([
  [{ code: "invalid_credentials", message: "x" }, "errors.invalid_credentials"],
  [{ code: "account_locked", message: "x" }, "errors.account_locked"],
  [{ code: "something_new", message: "x" }, "errors.unknown"], // newer controller
  [{ detail: [{ loc: ["body", "code"], msg: "x" }] }, "errors.invalid_input"], // 422
  [new TypeError("Failed to fetch"), "errors.network"],
  [undefined, "errors.unknown"],
  ["text", "errors.unknown"],
])("errorKey(%j) = %s", (error, key) => {
  expect(errorKey(error)).toBe(key);
});

test("the inherited properties are not error codes", () => {
  expect(errorKey({ code: "toString" })).toBe("errors.unknown");
});

test("a TOTP key is shown by groups of four", () => {
  expect(groupSecret("JBSWY3DPEHPK3PXP")).toBe("JBSW Y3DP EHPK 3PXP");
  expect(groupSecret("ABCDEF")).toBe("ABCD EF");
});
