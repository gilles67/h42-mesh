// Entry point: loads the Mantine styles and draws the application in the
// <div id="root"> of index.html.
import "@mantine/core/styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { Providers, createQueryClient } from "./Providers";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html has no #root element");
}

createRoot(root).render(
  <StrictMode>
    <Providers queryClient={createQueryClient()}>
      <App />
    </Providers>
  </StrictMode>,
);
