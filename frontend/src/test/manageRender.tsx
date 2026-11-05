/** Render de la página pública `/g/:token` con reloj fijo y un QueryClient "externo" de la app. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ManagePage from "../pages/ManagePage";
import { NowProvider } from "../shared/time/now";
import { AHORA, TOKEN } from "./manageFixtures";

export function abrirGestion(): ReturnType<typeof userEvent.setup> {
  // La página debe usar su PROPIO QueryClient (D14): este externo no se usa.
  const externo = new QueryClient();
  render(
    <QueryClientProvider client={externo}>
      <NowProvider clock={() => AHORA}>
        <MemoryRouter initialEntries={[`/g/${TOKEN}`]}>
          <Routes>
            <Route path="/g/:token" element={<ManagePage />} />
            <Route path="/login" element={<p>Pantalla de login</p>} />
          </Routes>
        </MemoryRouter>
      </NowProvider>
    </QueryClientProvider>
  );
  return userEvent.setup();
}
