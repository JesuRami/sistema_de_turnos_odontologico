/** Umbral de costo mensual de WhatsApp en Políticas (C-14, D8). */
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { ClinicPolicies } from "../../shared/api/types";
import { POLICIES } from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import PoliciesPage from "./PoliciesPage";

const CAMPO = "Alerta de costo mensual de WhatsApp (US$)";

function servidor(inicial: ClinicPolicies): unknown[] {
  let actuales = inicial;
  const cuerpos: unknown[] = [];
  server.use(
    http.get("/api/clinic/policies", () => HttpResponse.json(actuales)),
    http.patch("/api/clinic/policies", async ({ request }) => {
      const body = (await request.json()) as { whatsapp_monthly_alert_usd?: string };
      cuerpos.push(body);
      const valor = body.whatsapp_monthly_alert_usd;
      actuales = {
        ...actuales,
        whatsapp_monthly_alert_usd: valor === undefined || Number(valor) === 0 ? null : Number(valor).toFixed(6)
      };
      return HttpResponse.json(actuales);
    })
  );
  return cuerpos;
}

describe("alerta de costo de WhatsApp en políticas", () => {
  it("el admin fija el umbral y solo se manda ese campo", async () => {
    const cuerpos = servidor(POLICIES);
    const { user } = renderWithProviders(<PoliciesPage />, { session: await loggedSession(makeUser("admin")) });

    await user.type(await screen.findByLabelText(CAMPO), "25.5");
    await user.click(screen.getByRole("button", { name: "Guardar políticas" }));

    expect(await screen.findByText("Políticas guardadas")).toBeInTheDocument();
    expect(cuerpos).toEqual([{ whatsapp_monthly_alert_usd: "25.5" }]);
  });

  it("vaciar el campo apaga la alerta (manda 0)", async () => {
    const cuerpos = servidor({ ...POLICIES, whatsapp_monthly_alert_usd: "10.000000" });
    const { user } = renderWithProviders(<PoliciesPage />, { session: await loggedSession(makeUser("admin")) });

    await user.clear(await screen.findByLabelText(CAMPO));
    await user.click(screen.getByRole("button", { name: "Guardar políticas" }));

    expect(await screen.findByText("Políticas guardadas")).toBeInTheDocument();
    expect(cuerpos).toEqual([{ whatsapp_monthly_alert_usd: "0" }]);
  });

  it("recepción ve el umbral como texto", async () => {
    servidor({ ...POLICIES, whatsapp_monthly_alert_usd: "10.000000" });
    renderWithProviders(<PoliciesPage />, { session: await loggedSession(makeUser("recepcion")) });

    expect(await screen.findByText("US$ 10.000000")).toBeInTheDocument();
  });
});
