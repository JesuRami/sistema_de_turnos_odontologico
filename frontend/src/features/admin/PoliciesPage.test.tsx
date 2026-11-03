import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { ClinicPolicies } from "../../shared/api/types";
import { agendaHandlers, POLICIES } from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import PoliciesPage from "./PoliciesPage";

describe("PoliciesPage", () => {
  it("el admin cambia el tope de sobreturnos y lo ve al recargar", async () => {
    let actuales: ClinicPolicies = POLICIES;
    const cuerpos: unknown[] = [];
    server.use(
      http.get("/api/clinic/policies", () => HttpResponse.json(actuales)),
      http.patch("/api/clinic/policies", async ({ request }) => {
        const body = (await request.json()) as Partial<ClinicPolicies>;
        cuerpos.push(body);
        actuales = { ...actuales, ...body };
        return HttpResponse.json(actuales);
      }),
      ...agendaHandlers()
    );
    const { user } = renderWithProviders(<PoliciesPage />, {
      session: await loggedSession(makeUser("admin"))
    });

    const tope = await screen.findByLabelText("Tope de sobreturnos por profesional y día");
    await user.clear(tope);
    await user.type(tope, "3");
    await user.click(screen.getByRole("button", { name: "Guardar políticas" }));

    expect(await screen.findByText("Políticas guardadas")).toBeInTheDocument();
    expect(cuerpos).toEqual([{ max_overbookings_per_day: 3 }]);
    await waitFor(() =>
      expect(screen.getByLabelText("Tope de sobreturnos por profesional y día")).toHaveValue(3)
    );
  });

  it("edita los pasos de recordatorio", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      http.patch("/api/clinic/policies", async ({ request }) => {
        cuerpos.push(await request.json());
        return HttpResponse.json(POLICIES);
      }),
      ...agendaHandlers()
    );
    const { user } = renderWithProviders(<PoliciesPage />, {
      session: await loggedSession(makeUser("admin"))
    });

    await user.click(await screen.findByRole("button", { name: "Agregar paso" }));
    const horas = screen.getAllByLabelText("Horas antes");
    await user.clear(horas[2] as HTMLElement);
    await user.type(horas[2] as HTMLElement, "3");
    await user.click(screen.getByRole("button", { name: "Guardar políticas" }));

    await waitFor(() =>
      expect(cuerpos).toEqual([
        {
          reminder_steps: [
            { offset_h: 72, channel: "whatsapp" },
            { offset_h: 24, channel: "whatsapp" },
            { offset_h: 3, channel: "whatsapp" }
          ]
        }
      ])
    );
  });

  it("muestra el error de la API", async () => {
    server.use(
      http.patch("/api/clinic/policies", () =>
        HttpResponse.json({ detail: [{ loc: ["body"] }] }, { status: 422 })
      ),
      ...agendaHandlers()
    );
    const { user } = renderWithProviders(<PoliciesPage />, {
      session: await loggedSession(makeUser("admin"))
    });
    const ventana = await screen.findByLabelText("Ventana de cancelación (horas)");
    await user.clear(ventana);
    await user.type(ventana, "9999");
    await user.click(screen.getByRole("button", { name: "Guardar políticas" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Revisá los datos ingresados");
  });

  it("recepción las ve en solo lectura", async () => {
    server.use(...agendaHandlers());
    renderWithProviders(<PoliciesPage />, { session: await loggedSession(makeUser("recepcion")) });

    expect(await screen.findByText("24 h")).toBeInTheDocument();
    expect(screen.getByText("72 h y 24 h antes (WhatsApp)")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Guardar políticas" })).not.toBeInTheDocument();
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  });
});
