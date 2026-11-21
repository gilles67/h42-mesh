// Translation setup: English only for now. Every displayed text comes from
// en.json through a key, so that other languages can be added later.
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./en.json";

export const resources = { en: { translation: en } } as const;

void i18n.use(initReactI18next).init({
  lng: "en",
  fallbackLng: "en",
  resources,
  interpolation: { escapeValue: false }, // React already escapes the values
});

export default i18n;
