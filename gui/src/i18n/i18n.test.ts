// Every key written in the components exists in en.json (TypeScript checks
// it too; this test also covers keys built at run time from literals).
import en from "./en.json";

const sources = import.meta.glob<string>(["../**/*.tsx", "!../**/*.test.tsx"], {
  query: "?raw",
  import: "default",
  eager: true,
});

function hasKey(key: string): boolean {
  let node: unknown = en;
  for (const part of key.split(".")) {
    if (typeof node !== "object" || node === null || !(part in node)) {
      return false;
    }
    node = (node as Record<string, unknown>)[part];
  }
  return typeof node === "string";
}

test("the keys used exist", () => {
  const pattern = /(?:\bt\(|i18nKey=)\s*["']([a-zA-Z0-9_.]+)["']/g;
  const used = Object.values(sources).flatMap((text) =>
    [...text.matchAll(pattern)].map((match) => match[1] ?? ""),
  );
  expect(used.length).toBeGreaterThan(0);
  expect(used.filter((key) => !hasKey(key))).toEqual([]);
});
