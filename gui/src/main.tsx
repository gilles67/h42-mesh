// Entry point: loads the Mantine styles and draws the application in the
// <div id="root"> of index.html. The AuthGate shows the login screens until
// someone is logged in; BrowserRouter follows the address of the page.
import "@mantine/core/styles.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";

import { App } from "./App";
import { AuthGate } from "./auth/AuthGate";
import { Providers, createQueryClient } from "./Providers";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html has no #root element");
}

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <Providers queryClient={createQueryClient()}>
        <AuthGate>
          <App />
        </AuthGate>
      </Providers>
    </BrowserRouter>
  </StrictMode>,
);
