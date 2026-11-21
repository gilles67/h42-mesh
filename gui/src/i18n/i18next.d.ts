// Gives TypeScript the list of keys of en.json: t("health.ok") is checked,
// a missing or misspelt key is a compilation error.
import "i18next";

import type en from "./en.json";

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "translation";
    resources: { translation: typeof en };
  }
}
