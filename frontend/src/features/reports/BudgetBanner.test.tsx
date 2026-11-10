import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { WhatsAppBudget } from "../../shared/api/types";
import { BUDGET_DISABLED } from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import { BudgetBanner } from "./BudgetBanner";

function presupuesto(overrides: Partial<WhatsAppBudget>): WhatsAppBudget {
  return { ...BUDGET_DISABLED, threshold_usd: "10.000000", ...overrides };
}

describe("BudgetBanner (C-14, SU-07)", () => {
  it.each([
    ["warning", "Presupuesto de WhatsApp al 80 %."],
    ["exceeded", "Presupuesto de WhatsApp superado."]
  ] as const)("con estado %s avisa sin cortar envíos", async (status, texto) => {
    server.use(
      http.get("/api/reports/whatsapp/budget", () =>
        HttpResponse.json(presupuesto({ status, spent_usd: "9.000000", used_pct: 90 }))
      )
    );
    renderWithProviders(<BudgetBanner enabled />, { session: await loggedSession(makeUser("admin")) });

    const aviso = await screen.findByRole("status");
    expect(aviso).toHaveTextContent(texto);
    expect(aviso).toHaveTextContent("US$ 9.000000 de US$ 10.000000");
    expect(aviso).toHaveTextContent("se siguen enviando");
  });

  it("en ok o sin umbral no muestra nada", async () => {
    server.use(http.get("/api/reports/whatsapp/budget", () => HttpResponse.json(presupuesto({ status: "ok" }))));
    renderWithProviders(<BudgetBanner enabled />, { session: await loggedSession(makeUser("admin")) });

    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("deshabilitado (no admin) no consulta la API", async () => {
    // Sin handler: MSW falla ante cualquier pedido no esperado.
    renderWithProviders(<BudgetBanner enabled={false} />, { session: await loggedSession(makeUser("recepcion")) });
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
