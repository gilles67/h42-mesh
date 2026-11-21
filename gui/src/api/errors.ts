// Turns an API error into a translation key. The controller answers
// {"code": "invalid_credentials", "message": "…"}: the code is stable, the
// English message is not shown (the GUI translates the code).
import en from "../i18n/en.json";

type ErrorName = keyof typeof en.errors;
export type ErrorKey = `errors.${ErrorName}`;

function isKnown(code: string): code is ErrorName {
  return Object.hasOwn(en.errors, code);
}

export function errorKey(error: unknown): ErrorKey {
  if (error instanceof TypeError) {
    return "errors.network"; // fetch failed: no answer at all
  }
  if (typeof error === "object" && error !== null) {
    if ("code" in error && typeof error.code === "string" && isKnown(error.code)) {
      return `errors.${error.code}`;
    }
    if ("detail" in error) {
      return "errors.invalid_input"; // 422: a field refused by the controller
    }
  }
  return "errors.unknown";
}
