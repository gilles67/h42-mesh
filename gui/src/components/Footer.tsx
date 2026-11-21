// Footer with the attribution required by the GeoLite2 licence (the ISP of
// the connections comes from the MaxMind database). The sentence is in en.json;
// <Trans> puts the link where <url>…</url> is ("link" would be read as the
// empty HTML element <link>).
import { Anchor, Center, Text } from "@mantine/core";
import { Trans } from "react-i18next";

export const MAXMIND_URL = "https://www.maxmind.com";

export function Footer() {
  return (
    <Center h="100%" px="md">
      <Text size="xs" c="dimmed" ta="center">
        <Trans
          i18nKey="footer.maxmind"
          components={{ url: <Anchor href={MAXMIND_URL} target="_blank" rel="noreferrer" inherit /> }}
        />
      </Text>
    </Center>
  );
}
