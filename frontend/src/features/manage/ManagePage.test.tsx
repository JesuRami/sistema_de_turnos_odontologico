import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import {
  TELEFONO,
  TOKEN,
  URL_VISTA,
  cancelled,
  confirmed,
  view,
  viewHandler
} from "../../test/manageFixtures";
import { abrirGestion } from "../../test/manageRender";
import { server } from "../../test/server";

describe("ManagePage — vista del turno", () => {
  it("turno pendiente: resumen en la zona de la clínica y las tres acciones", async () => {
    server.use(viewHandler());
    abrirGestion();

    expect(await screen.findByText(/Hola, María/)).toBeInTheDocument();
    // 13:00Z con el navegador en UTC: se muestra la hora de Buenos Aires.
    expect(screen.getByRole("heading", { name: "lun 14/01 · 10:00" })).toBeInTheDocument();
    expect(screen.getByText(/Dra\. Ficticia Uno/)).toBeInTheDocument();
    expect(screen.getByText("Pendiente")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirmar turno" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Cambiar horario" })).toBeEnabled();
    expect(screen.queryByText("Pantalla de login")).not.toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toContain(TOKEN);
  });

  it("turno confirmado: no ofrece confirmar", async () => {
    server.use(viewHandler(confirmed()));
    abrirGestion();

    expect(await screen.findByText("Confirmado")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirmar turno" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeEnabled();
  });

  it("fuera de la ventana: cancelar y cambiar deshabilitados con el teléfono de la clínica", async () => {
    server.use(
      viewHandler(
        view({ actions: { can_cancel: false, can_reschedule: false, blocked_reason: "window_closed" } })
      )
    );
    abrirGestion();

    expect(await screen.findByRole("button", { name: "Cancelar" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cambiar horario" })).toBeDisabled();
    const telefono = screen.getByRole("link", { name: /Llamar a la clínica/ });
    expect(telefono).toHaveAttribute("href", `tel:${TELEFONO}`);
    expect(screen.getByText(/Faltan menos de 24 h/)).toBeInTheDocument();
  });

  it("turno cancelado: sin acciones y con volver a reservar", async () => {
    server.use(viewHandler(cancelled()));
    abrirGestion();

    expect(await screen.findByText("Cancelado")).toBeInTheDocument();
    for (const nombre of ["Confirmar turno", "Cancelar", "Cambiar horario"]) {
      expect(screen.queryByRole("button", { name: nombre })).not.toBeInTheDocument();
    }
    expect(screen.getByRole("link", { name: "Reservar un turno nuevo" })).toHaveAttribute(
      "href",
      "/b/clinica-demo"
    );
  });

  it("anuncia la carga con aria-live", async () => {
    server.use(
      http.get(URL_VISTA, async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
        return HttpResponse.json(view());
      })
    );
    abrirGestion();

    const estado = screen.getByText("Cargando tu turno…");
    expect(estado.closest("[aria-live]")).not.toBeNull();
    expect(await screen.findByText(/Hola, María/)).toBeInTheDocument();
  });

  it("no indexa ni filtra la URL por Referer", async () => {
    server.use(viewHandler());
    abrirGestion();
    await screen.findByText(/Hola, María/);

    expect(document.querySelector('meta[name="referrer"]')).toHaveAttribute("content", "no-referrer");
    expect(document.querySelector('meta[name="robots"]')).toHaveAttribute("content", "noindex");
  });
});
