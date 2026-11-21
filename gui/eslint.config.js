// ESLint: code analysis. The i18next rule refuses text written directly in
// the components: every displayed text goes through a translation key.
import js from "@eslint/js";
import { defineConfig } from "eslint/config";
import i18next from "eslint-plugin-i18next";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default defineConfig(
  { ignores: ["dist", "src/api/schema.d.ts"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, tseslint.configs.strict],
    languageOptions: { globals: globals.browser },
    plugins: { "react-hooks": reactHooks },
    rules: reactHooks.configs.recommended.rules,
  },
  {
    files: ["src/**/*.tsx"],
    ignores: ["src/**/*.test.tsx", "src/test/**"],
    plugins: { i18next },
    rules: {
      // Text between tags, and the attributes read by people; not the
      // technical props of Mantine (size="xs", color="red"…).
      "i18next/no-literal-string": [
        "error",
        {
          mode: "jsx-only",
          // Calls whose strings are not texts: the defaults of the plugin
          // (t, i18n…), plus the names of form fields: form.getInputProps("name").
          callees: {
            exclude: [
              "i18n(ext)?",
              "t",
              "require",
              "addEventListener",
              "removeEventListener",
              "postMessage",
              "getElementById",
              "dispatch",
              "commit",
              "includes",
              "indexOf",
              "endsWith",
              "startsWith",
              "getInputProps$",
            ],
          },
          "jsx-attributes": {
            include: ["aria-label", "title", "alt", "placeholder", "label", "description", "error"],
          },
        },
      ],
    },
  },
);
