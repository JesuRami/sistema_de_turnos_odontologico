import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { PilotMetric, PilotReport } from "../../shared/api/types";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import { PilotPanel } from "./PilotPanel";

const RANGO = { from: "2030-01-01", to: "2030-01-31" };

function metrica(key: string, overrides: Partial<PilotMetric> = {}): PilotMetric {
  return { key, value: 0.5, target: 0.6, met: false, numerator: 1, denominator: 2, ...overrides };
}

function informe(overrides: Partial<PilotReport> = {}): PilotReport {
  return {
    from_date: RANGO.from,
    to_date: RANGO.to,
    overlaps: 0,
    overlaps_ok: true,
    no_show: metrica("no_show_rate", { value: 0.12, target: null, met: null, numerator: 3, denominator: 25 }),
    confirmation_before_24h: metrica("confirmation_before_24h_rate", { value: 0.7, met: true, numerator: 7, denominator: 10 }),
    waitlist_recovery: metrica("waitlist_recovery_rate", { value: null, target: 0.1, met: null, numerator: 0, denominator: 0 }),
    online_share: metrica("online_share", { value: 0.25, target: 0.3, met: false, numerator: 5, denominator: 20 }),
    ...overrides
  };
}

describe("PilotPanel (C-14)", () => {
  it("muestra cada métrica con su base, su meta y si cumple", async () => {
    server.use(http.get("/api/reports/pilot", () => HttpResponse.json(informe())));
    renderWithProviders(<PilotPanel range={RANGO} />, { session: await loggedSession(makeUser("admin")) });

    const tabla = await screen.findByRole("table", { name: "Métricas de éxito del piloto" });
    const fila = (nombre: string): HTMLElement => within(tabla).getByRole("row", { name: new RegExp(nombre) });
    expect(fila("Confirmados antes")).toHaveTextContent("70 %");
    expect(fila("Confirmados antes")).toHaveTextContent("7 / 10");
    expect(fila("Confirmados antes")).toHaveTextContent("Cumple");
    expect(fila("online")).toHaveTextContent("No cumple");
    expect(fila("Huecos recuperados")).toHaveTextContent("Sin datos suficientes");
    expect(screen.getByText(/0 turnos superpuestos/)).toBeInTheDocument();
  });

  it("manda la línea base de ausentismo y muestra la variación", async () => {
    const pedidos: URLSearchParams[] = [];
    server.use(
      http.get("/api/reports/pilot", ({ request }) => {
        const params = new URL(request.url).searchParams;
        pedidos.push(params);
        return HttpResponse.json(
          params.get("baseline_no_show_pct") === null
            ? informe()
            : informe({
                no_show: metrica("no_show_rate", {
                  value: 0.12,
                  target: null,
                  met: true,
                  baseline_pct: 20,
                  delta_vs_baseline_pct: -40
                })
              })
        );
      })
    );
    const { user } = renderWithProviders(<PilotPanel range={RANGO} />, {
      session: await loggedSession(makeUser("admin"))
    });

    await user.type(screen.getByLabelText("Ausentismo previo de la clínica (%)"), "20");

    await waitFor(() => expect(pedidos[pedidos.length - 1]?.get("baseline_no_show_pct")).toBe("20"));
    expect(await screen.findByText(/−40|-40/)).toBeInTheDocument();
  });

  it("avisa si la integridad de agenda no da cero", async () => {
    server.use(http.get("/api/reports/pilot", () => HttpResponse.json(informe({ overlaps: 2, overlaps_ok: false }))));
    renderWithProviders(<PilotPanel range={RANGO} />, { session: await loggedSession(makeUser("admin")) });

    expect(await screen.findByRole("alert")).toHaveTextContent("2 pares de turnos superpuestos");
  });
});
