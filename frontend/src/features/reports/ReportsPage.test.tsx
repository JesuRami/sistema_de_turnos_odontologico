import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  AbsenteeismReport,
  AuditEvent,
  CancellationsReport,
  OccupancyReport,
  Page
} from "../../shared/api/types";
import { RequireRole } from "../../shared/auth/guards";
import { agendaHandlers } from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import ReportsPage from "./ReportsPage";

const AHORA = (): Date => new Date("2030-01-15T15:00:00Z");

const OCUPACION: OccupancyReport = {
  group_by: "professional",
  from_date: "2030-01-01",
  to_date: "2030-01-31",
  capacity_basis: "current_schedule",
  rows: [
    {
      resource_id: "prof-1",
      resource_name: "Dra. Ficticia Uno",
      appointments: 2,
      overbookings: 0,
      booked_min: 120,
      capacity_min: 480,
      occupancy_pct: 25
    }
  ],
  totals: { appointments: 2, overbookings: 0, booked_min: 120, capacity_min: 480, occupancy_pct: 25 }
};

const AUSENTISMO: AbsenteeismReport = {
  from_date: "2030-01-01",
  to_date: "2030-01-31",
  rows: [
    {
      professional_id: "prof-1",
      professional_name: "Dra. Ficticia Uno",
      present: 6,
      absent: 1,
      no_show: 2,
      late_cancellations: 1,
      outcomes: 10,
      no_show_rate: 0.2,
      absent_rate: 0.1,
      late_cancellation_rate: 0.1
    }
  ],
  totals: {
    present: 6,
    absent: 1,
    no_show: 2,
    late_cancellations: 1,
    outcomes: 10,
    no_show_rate: 0.2,
    absent_rate: 0.1,
    late_cancellation_rate: 0.1
  }
};

const CANCELACIONES: CancellationsReport = {
  from_date: "2030-01-01",
  to_date: "2030-01-31",
  total: 3,
  rows: [
    { reason: "paciente", total: 2, late: 1, in_window: 1 },
    { reason: "profesional", total: 0, late: 0, in_window: 0 },
    { reason: "clinica", total: 1, late: 0, in_window: 1 },
    { reason: "bloqueo", total: 0, late: 0, in_window: 0 },
    { reason: "otro", total: 0, late: 0, in_window: 0 }
  ]
};

function evento(n: number): AuditEvent {
  return {
    id: `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`,
    appointment_id: `11111111-0000-0000-0000-${String(n).padStart(12, "0")}`,
    event: "created",
    actor_type: "user",
    actor_user_id: "22222222-aaaa-bbbb-cccc-000000000001",
    from_status: null,
    to_status: "confirmed",
    payload: {},
    created_at: "2030-01-10T13:00:00Z"
  };
}

function handlersBase(): void {
  server.use(
    ...agendaHandlers(),
    http.get("/api/reports/occupancy", () => HttpResponse.json(OCUPACION)),
    http.get("/api/reports/absenteeism", () => HttpResponse.json(AUSENTISMO)),
    http.get("/api/reports/cancellations", () => HttpResponse.json(CANCELACIONES)),
    http.get("/api/audit/appointments", () =>
      HttpResponse.json({ items: [evento(1)], next_cursor: null } satisfies Page<AuditEvent>)
    )
  );
}

async function renderAdmin(): Promise<ReturnType<typeof renderWithProviders>> {
  return renderWithProviders(<ReportsPage />, {
    session: await loggedSession(makeUser("admin")),
    now: AHORA
  });
}

describe("ReportsPage", () => {
  beforeEach(() => {
    handlersBase();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("solo el admin entra: recepción ve el aviso de permiso", async () => {
    renderWithProviders(
      <RequireRole roles={["admin"]}>
        <ReportsPage />
      </RequireRole>,
      { session: await loggedSession(makeUser("recepcion")), now: AHORA }
    );

    expect(await screen.findByText("No tenés permiso para esta sección")).toBeInTheDocument();
    expect(screen.queryByRole("tablist", { name: "Reportes" })).not.toBeInTheDocument();
  });

  it("muestra las cuatro pestañas y el mes en curso en la hora de la clínica", async () => {
    await renderAdmin();

    expect(await screen.findByRole("tab", { name: "Ocupación" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    for (const nombre of ["Ausentismo", "Cancelaciones", "Auditoría"]) {
      expect(screen.getByRole("tab", { name: nombre })).toBeInTheDocument();
    }
    expect(screen.getByLabelText("Desde")).toHaveValue("2030-01-01");
    expect(screen.getByLabelText("Hasta")).toHaveValue("2030-01-31");
  });

  it("pide la ocupación con el rango y muestra la nota de horario vigente", async () => {
    const pedidos: URLSearchParams[] = [];
    server.use(
      http.get("/api/reports/occupancy", ({ request }) => {
        pedidos.push(new URL(request.url).searchParams);
        return HttpResponse.json(OCUPACION);
      })
    );
    await renderAdmin();

    expect(await screen.findByText("Dra. Ficticia Uno")).toBeInTheDocument();
    expect(screen.getByText(/horario vigente de la agenda/)).toBeInTheDocument();
    expect(screen.getAllByText("25 %").length).toBeGreaterThan(0);
    expect(pedidos[0]?.get("from")).toBe("2030-01-01");
    expect(pedidos[0]?.get("to")).toBe("2030-01-31");
    expect(pedidos[0]?.get("group_by")).toBe("professional");
  });

  it("agrupar por sillón vuelve a pedir el reporte", async () => {
    const grupos: (string | null)[] = [];
    server.use(
      http.get("/api/reports/occupancy", ({ request }) => {
        grupos.push(new URL(request.url).searchParams.get("group_by"));
        return HttpResponse.json(OCUPACION);
      })
    );
    const { user } = await renderAdmin();
    await screen.findByText("Dra. Ficticia Uno");

    await user.selectOptions(screen.getByLabelText("Agrupar por"), "chair");

    await waitFor(() => expect(grupos).toContain("chair"));
  });

  it("ausentismo separa «no vino», «ausente con aviso» y cancelación tardía", async () => {
    const { user } = await renderAdmin();

    await user.click(await screen.findByRole("tab", { name: "Ausentismo" }));

    const tabla = await screen.findByRole("table", { name: "Ausentismo por profesional" });
    const columnas = within(tabla).getAllByRole("columnheader").map((c) => c.textContent);
    expect(columnas).toEqual([
      "Profesional",
      "Asistieron",
      "Ausente con aviso",
      "No vino",
      "Cancelación tardía",
      "Tasa «no vino»"
    ]);
    expect(within(tabla).getAllByText("20 %").length).toBeGreaterThan(0);
  });

  it("cancelaciones lista cada motivo con su corte", async () => {
    const { user } = await renderAdmin();

    await user.click(await screen.findByRole("tab", { name: "Cancelaciones" }));

    const tabla = await screen.findByRole("table", { name: "Cancelaciones por motivo" });
    expect(within(tabla).getByRole("row", { name: /Paciente 2 1 1/ })).toBeInTheDocument();
    expect(within(tabla).getByRole("row", { name: /Clínica 1 0 1/ })).toBeInTheDocument();
  });

  it("sin datos muestra un mensaje de vacío, no una tabla de ceros", async () => {
    server.use(
      http.get("/api/reports/cancellations", () =>
        HttpResponse.json({ ...CANCELACIONES, total: 0 } satisfies CancellationsReport)
      )
    );
    const { user } = await renderAdmin();

    await user.click(await screen.findByRole("tab", { name: "Cancelaciones" }));

    expect(await screen.findByText("No hubo cancelaciones en este período.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("un 422 de rango se explica en lenguaje claro y conserva los filtros", async () => {
    server.use(
      http.get("/api/reports/occupancy", () =>
        HttpResponse.json({ detail: "range_too_large" }, { status: 422 })
      )
    );
    await renderAdmin();

    expect(await screen.findByRole("alert")).toHaveTextContent("el máximo es de un año");
    expect(screen.getByLabelText("Desde")).toHaveValue("2030-01-01");
    expect(screen.getByLabelText("Hasta")).toHaveValue("2030-01-31");
  });

  it("un rango invertido avisa y no consulta el backend", async () => {
    let pedidos = 0;
    server.use(
      http.get("/api/reports/occupancy", () => {
        pedidos += 1;
        return HttpResponse.json(OCUPACION);
      })
    );
    await renderAdmin();
    await screen.findByText("Dra. Ficticia Uno");
    const antes = pedidos;

    fireEvent.change(screen.getByLabelText("Desde"), { target: { value: "2030-02-15" } });

    expect(
      await screen.findByText("La fecha inicial debe ser anterior o igual a la final.")
    ).toBeInTheDocument();
    expect(pedidos).toBe(antes);
  });

  it("descarga el CSV del reporte con la sesión y sin credenciales en la URL", async () => {
    const urls: string[] = [];
    const autorizaciones: (string | null)[] = [];
    server.use(
      http.get("/api/reports/absenteeism", ({ request }) => {
        if (new URL(request.url).searchParams.get("format") === "csv") {
          urls.push(request.url);
          autorizaciones.push(request.headers.get("authorization"));
          return new HttpResponse("professional_id,present\r\n", {
            headers: { "Content-Type": "text/csv" }
          });
        }
        return HttpResponse.json(AUSENTISMO);
      })
    );
    const nombres: string[] = [];
    URL.createObjectURL = vi.fn(() => "blob:prueba");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement
    ) {
      nombres.push(this.download);
    });
    const { user } = await renderAdmin();
    await user.click(await screen.findByRole("tab", { name: "Ausentismo" }));

    await user.click(await screen.findByRole("button", { name: "Descargar CSV" }));

    await waitFor(() => expect(nombres).toEqual(["ausentismo-2030-01-01-2030-01-31.csv"]));
    expect(urls[0]).toContain("from=2030-01-01");
    expect(urls[0]).not.toMatch(/token|bearer|acceso-test/i);
    expect(autorizaciones[0]).toBe("Bearer acceso-test");
  });

  it("«Exportar todos mis datos» pide el ZIP en el formato elegido", async () => {
    const formatos: (string | null)[] = [];
    server.use(
      http.get("/api/exports/full", ({ request }) => {
        formatos.push(new URL(request.url).searchParams.get("format"));
        return new HttpResponse(new Uint8Array([80, 75, 3, 4]), {
          headers: { "Content-Type": "application/zip" }
        });
      })
    );
    const nombres: string[] = [];
    URL.createObjectURL = vi.fn(() => "blob:zip");
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement
    ) {
      nombres.push(this.download);
    });
    const { user } = await renderAdmin();
    await screen.findByText("Dra. Ficticia Uno");

    await user.selectOptions(screen.getByLabelText("Formato de la exportación"), "json");
    await user.click(screen.getByRole("button", { name: "Exportar todos mis datos" }));

    await waitFor(() => expect(nombres).toEqual(["export-completo.zip"]));
    expect(formatos).toEqual(["json"]);
  });

  it("un fallo de la descarga se informa sin perder la pantalla", async () => {
    server.use(
      http.get("/api/exports/full", () => HttpResponse.json({ detail: "forbidden_role" }, { status: 403 }))
    );
    const { user } = await renderAdmin();
    await screen.findByText("Dra. Ficticia Uno");

    await user.click(screen.getByRole("button", { name: "Exportar todos mis datos" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No tenés permiso");
    expect(screen.getByRole("tab", { name: "Ocupación" })).toBeInTheDocument();
  });

  it("auditoría: «Cargar más» agrega la página siguiente sin repetir filas", async () => {
    const cursores: (string | null)[] = [];
    server.use(
      http.get("/api/audit/appointments", ({ request }) => {
        const cursor = new URL(request.url).searchParams.get("cursor");
        cursores.push(cursor);
        return HttpResponse.json(
          cursor === null
            ? { items: [evento(1), evento(2)], next_cursor: "c2" }
            : { items: [evento(3)], next_cursor: null }
        );
      })
    );
    const { user } = await renderAdmin();
    await user.click(await screen.findByRole("tab", { name: "Auditoría" }));
    const tabla = await screen.findByRole("table", { name: "Auditoría de turnos" });
    expect(within(tabla).getAllByRole("row")).toHaveLength(3);

    await user.click(screen.getByRole("button", { name: "Cargar más" }));

    await waitFor(() => expect(within(tabla).getAllByRole("row")).toHaveLength(4));
    expect(cursores).toEqual([null, "c2"]);
    expect(screen.queryByRole("button", { name: "Cargar más" })).not.toBeInTheDocument();
  });

  it("auditoría: filtra por tipo de evento", async () => {
    const tipos: (string | null)[] = [];
    server.use(
      http.get("/api/audit/appointments", ({ request }) => {
        tipos.push(new URL(request.url).searchParams.get("event"));
        return HttpResponse.json({ items: [evento(1)], next_cursor: null });
      })
    );
    const { user } = await renderAdmin();
    await user.click(await screen.findByRole("tab", { name: "Auditoría" }));
    await screen.findByRole("table", { name: "Auditoría de turnos" });

    await user.selectOptions(screen.getByLabelText("Tipo de evento"), "cancelled");

    await waitFor(() => expect(tipos).toContain("cancelled"));
  });
});
