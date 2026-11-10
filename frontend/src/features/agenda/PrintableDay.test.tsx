import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { agendaHandlers, appointment, chair } from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import PrintableDay from "./PrintableDay";

const AHORA = (): Date => new Date("2030-01-07T11:00:00Z");

describe("agenda del día imprimible (C-14, SU-06)", () => {
  it("lista los turnos vigentes del día por sillón, en la hora de la clínica", async () => {
    const pedidos: URLSearchParams[] = [];
    server.use(...agendaHandlers({ chairs: [chair(), chair({ id: "chair-2", name: "Sillón 2" })] }));
    server.use(
      http.get("/api/appointments", ({ request }) => {
        pedidos.push(new URL(request.url).searchParams);
        return HttpResponse.json({
          items: [
            appointment({ id: "a2", starts_at: "2030-01-07T15:00:00Z", ends_at: "2030-01-07T15:30:00Z" }),
            appointment({ id: "a1", origin: "online", status: "pending" }),
            appointment({
              id: "a3",
              status: "cancelled",
              cancelled_at: "2030-01-06T10:00:00Z",
              cancellation_reason: "paciente",
              patient: { id: "pat-3", full_name: "Cancelado Ficticio", phone_e164: null, email: null }
            })
          ],
          next_cursor: null
        });
      })
    );
    renderWithProviders(<PrintableDay />, {
      route: "/agenda/imprimir?dia=2030-01-07",
      session: await loggedSession(makeUser("recepcion")),
      now: AHORA
    });

    expect(await screen.findByRole("heading", { name: "Agenda del lun 07/01" })).toBeInTheDocument();
    const tabla = screen.getByRole("table", { name: "Turnos de Sillón 1" });
    const filas = within(tabla).getAllByRole("row").slice(1);
    expect(filas.map((f) => within(f).getAllByRole("cell")[0]?.textContent)).toEqual([
      "10:00–10:30",
      "12:00–12:30"
    ]);
    expect(within(filas[0] as HTMLElement).getByText("Reserva online")).toBeInTheDocument();
    expect(screen.queryByText("Cancelado Ficticio")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sillón 2" }).nextElementSibling).toHaveTextContent("Sin turnos.");
    expect(pedidos[0]?.get("from")).toBe("2030-01-07T03:00:00.000Z");
  });

  it("el botón imprime con el diálogo del navegador", async () => {
    const imprimir = vi.spyOn(window, "print").mockImplementation(() => undefined);
    server.use(...agendaHandlers({ appointments: [appointment()] }));
    const { user } = renderWithProviders(<PrintableDay />, {
      route: "/agenda/imprimir",
      session: await loggedSession(makeUser("recepcion")),
      now: AHORA
    });

    await user.click(await screen.findByRole("button", { name: "Imprimir" }));
    expect(imprimir).toHaveBeenCalledOnce();
  });
});
