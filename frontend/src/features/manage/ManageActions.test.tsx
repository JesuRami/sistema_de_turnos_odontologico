import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it } from "vitest";
import {
  INICIO,
  TELEFONO,
  TOKEN,
  URL_VISTA,
  actionHandler,
  availability,
  cancelled,
  confirmed,
  slot,
  view,
  viewHandler
} from "../../test/manageFixtures";
import { abrirGestion } from "../../test/manageRender";
import { server } from "../../test/server";
import type { ManageActionRequest } from "./types";

// Lunes 14/01 en Buenos Aires: 11:00 y 11:30 libres; 10:00 es el horario actual.
const LUN_10 = slot(INICIO);
const LUN_11 = slot("2030-01-14T11:00:00-03:00");
const LUN_1130 = slot("2030-01-14T11:30:00-03:00");

function availabilityHandler(slots = [LUN_10, LUN_11, LUN_1130]): ReturnType<typeof http.get> {
  return http.get(`${URL_VISTA}/availability`, () => HttpResponse.json(availability(slots)));
}

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe("ManagePage — confirmar", () => {
  it("doble toque envía una sola acción y queda confirmado", async () => {
    const enviados: ManageActionRequest[] = [];
    server.use(
      viewHandler(),
      actionHandler(enviados, () => HttpResponse.json(confirmed()))
    );
    const user = abrirGestion();

    const boton = await screen.findByRole("button", { name: "Confirmar turno" });
    await user.dblClick(boton);

    expect(await screen.findByText("Confirmado")).toBeInTheDocument();
    expect(enviados).toEqual([{ action: "confirm" }]);
    expect(screen.queryByRole("button", { name: "Confirmar turno" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Tu turno quedó confirmado");
  });
});

describe("ManagePage — cancelar", () => {
  it("pide motivo opcional, confirma la acción destructiva y queda cancelado", async () => {
    const enviados: ManageActionRequest[] = [];
    server.use(viewHandler(), actionHandler(enviados, () => HttpResponse.json(cancelled())));
    const user = abrirGestion();

    await user.click(await screen.findByRole("button", { name: "Cancelar" }));
    const dialogo = await screen.findByRole("dialog", { name: "Cancelar turno" });
    await user.click(within(dialogo).getByLabelText("Viaje"));
    await user.click(within(dialogo).getByRole("button", { name: "Confirmar cancelación" }));

    expect(await screen.findByText("Cancelado")).toBeInTheDocument();
    expect(enviados).toEqual([{ action: "cancel", reason: "viaje" }]);
    expect(screen.queryByRole("button", { name: "Cancelar" })).not.toBeInTheDocument();
  });

  it("sin motivo la acción se envía igual; la nota solo con «Otro»", async () => {
    const enviados: ManageActionRequest[] = [];
    server.use(viewHandler(), actionHandler(enviados, () => HttpResponse.json(cancelled())));
    const user = abrirGestion();

    await user.click(await screen.findByRole("button", { name: "Cancelar" }));
    const dialogo = await screen.findByRole("dialog", { name: "Cancelar turno" });
    expect(within(dialogo).queryByLabelText(/Contanos brevemente/)).not.toBeInTheDocument();
    await user.click(within(dialogo).getByRole("button", { name: "Confirmar cancelación" }));

    await screen.findByText("Cancelado");
    expect(enviados).toEqual([{ action: "cancel" }]);
  });

  it("volver sin cancelar no envía nada", async () => {
    const enviados: ManageActionRequest[] = [];
    server.use(viewHandler(), actionHandler(enviados, () => HttpResponse.json(cancelled())));
    const user = abrirGestion();

    await user.click(await screen.findByRole("button", { name: "Cancelar" }));
    await user.click(await screen.findByRole("button", { name: "Volver sin cancelar" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(enviados).toEqual([]);
  });

  it("409 cancellation_window_closed deriva a la clínica y el turno sigue vigente", async () => {
    const enviados: ManageActionRequest[] = [];
    server.use(
      viewHandler(),
      actionHandler(enviados, () =>
        HttpResponse.json({ detail: "cancellation_window_closed" }, { status: 409 })
      )
    );
    const user = abrirGestion();

    await user.click(await screen.findByRole("button", { name: "Cancelar" }));
    const dialogo = await screen.findByRole("dialog", { name: "Cancelar turno" });
    await user.click(within(dialogo).getByRole("button", { name: "Confirmar cancelación" }));

    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent("Ya no podés cancelar online");
    expect(within(alerta).getByRole("link", { name: /Llamar a la clínica/ })).toHaveAttribute(
      "href",
      `tel:${TELEFONO}`
    );
    expect(screen.getByText("Pendiente")).toBeInTheDocument();
  });
});

describe("ManagePage — cambiar horario", () => {
  it("muestra solo los huecos del servidor, marca el actual y mueve el turno", async () => {
    const enviados: ManageActionRequest[] = [];
    server.use(
      viewHandler(),
      availabilityHandler(),
      actionHandler(enviados, () =>
        HttpResponse.json(view({ appointment: { starts_at: LUN_11.starts_at } }))
      )
    );
    const user = abrirGestion();

    await user.click(await screen.findByRole("button", { name: "Cambiar horario" }));
    await user.click(await screen.findByRole("button", { name: "lun 14/01" }));
    const actual = screen.getByRole("button", { name: /10:00/ });
    expect(actual).toHaveAttribute("aria-current", "true");
    expect(actual).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "11:00" }));
    await user.click(screen.getByRole("button", { name: "Confirmar 11:00" }));

    expect(await screen.findByRole("heading", { name: "lun 14/01 · 11:00" })).toBeInTheDocument();
    expect(enviados).toEqual([{ action: "reschedule", starts_at: LUN_11.starts_at }]);
  });

  it("409 slot_taken explica y ofrece los alternativos", async () => {
    const enviados: ManageActionRequest[] = [];
    server.use(
      viewHandler(),
      availabilityHandler(),
      actionHandler(enviados, (_body, n) =>
        n === 1
          ? HttpResponse.json(
              { detail: "slot_taken", alternatives: [LUN_1130] },
              { status: 409 }
            )
          : HttpResponse.json(view({ appointment: { starts_at: LUN_1130.starts_at } }))
      )
    );
    const user = abrirGestion();

    await user.click(await screen.findByRole("button", { name: "Cambiar horario" }));
    await user.click(await screen.findByRole("button", { name: "lun 14/01" }));
    await user.click(screen.getByRole("button", { name: "11:00" }));
    await user.click(screen.getByRole("button", { name: "Confirmar 11:00" }));

    const alerta = await screen.findByRole("alert");
    expect(alerta).toHaveTextContent("Ese horario se acaba de ocupar");
    await user.click(within(alerta).getByRole("button", { name: "Pasar a lun 14/01 · 11:30" }));

    expect(await screen.findByRole("heading", { name: "lun 14/01 · 11:30" })).toBeInTheDocument();
    expect(enviados).toEqual([
      { action: "reschedule", starts_at: LUN_11.starts_at },
      { action: "reschedule", starts_at: LUN_1130.starts_at }
    ]);
  });

  it("sin huecos muestra el teléfono de la clínica en lugar de una grilla vacía", async () => {
    server.use(viewHandler(), availabilityHandler([]));
    const user = abrirGestion();

    await user.click(await screen.findByRole("button", { name: "Cambiar horario" }));

    expect(await screen.findByText(/No hay horarios libres/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Llamar a la clínica/ })).toHaveAttribute(
      "href",
      `tel:${TELEFONO}`
    );
  });
});

describe("ManagePage — link vencido o inválido", () => {
  it("410 muestra la pantalla de contacto con la clínica y ninguna acción", async () => {
    server.use(
      http.get(URL_VISTA, () =>
        HttpResponse.json(
          { detail: "manage_link_expired", clinic: { name: "Clínica Demo Ficticia", phone: TELEFONO } },
          { status: 410 }
        )
      )
    );
    abrirGestion();

    expect(
      await screen.findByRole("heading", { name: "Este link ya no está disponible" })
    ).toBeInTheDocument();
    expect(screen.getByText("Clínica Demo Ficticia")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Llamar a la clínica/ })).toHaveAttribute(
      "href",
      `tel:${TELEFONO}`
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("404 muestra un mensaje genérico sin datos de turno", async () => {
    server.use(
      http.get(URL_VISTA, () =>
        HttpResponse.json({ detail: "manage_link_not_found" }, { status: 404 })
      )
    );
    abrirGestion();

    expect(
      await screen.findByRole("heading", { name: "Este link ya no está disponible" })
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("ManagePage — storage", () => {
  it("después de usar la página no queda el token ni datos del turno en el navegador", async () => {
    const enviados: ManageActionRequest[] = [];
    server.use(viewHandler(), actionHandler(enviados, () => HttpResponse.json(confirmed())));
    const user = abrirGestion();

    await user.click(await screen.findByRole("button", { name: "Confirmar turno" }));
    await screen.findByText("Confirmado");

    await waitFor(() => expect(enviados).toHaveLength(1));
    const guardado = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage });
    expect(guardado).not.toContain(TOKEN);
    expect(guardado).not.toContain("María");
    expect(document.cookie).not.toContain(TOKEN);
  });
});
