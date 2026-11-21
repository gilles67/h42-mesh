// Everything the components need around them: Mantine (styles), TanStack
// Query (calls to the API, cache) and the translations. Used by main.tsx and
// by the tests.
import { MantineProvider } from "@mantine/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { I18nextProvider } from "react-i18next";

import i18n from "./i18n";
import { theme } from "./theme";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { staleTime: 10_000, refetchOnWindowFocus: true } },
  });
}

type ProvidersProps = {
  children: ReactNode;
  queryClient: QueryClient;
};

export function Providers({ children, queryClient }: ProvidersProps) {
  return (
    <I18nextProvider i18n={i18n}>
      <MantineProvider theme={theme}>
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
      </MantineProvider>
    </I18nextProvider>
  );
}
