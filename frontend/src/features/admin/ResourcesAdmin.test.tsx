import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { agendaHandlers, chair, professional } from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import ChairsAdmin from "./ChairsAdmin";
import ProfessionalsAdmin from "./ProfessionalsAdmin";

async function render(ui: JSX.Element) {
  return renderWithProviders(ui, { session: await loggedSession(makeUser("admin")) });
}

describe("ProfessionalsAdmin", () => {
  it("lista profesionales sin opción de borrar", async () => {
    server.use(
      ...agendaHandlers({
        professionals: [professional(), professional({ id: "prof-2", display_name: "Dr. Inactivo", active: false })]
      })
    );
    await render(<ProfessionalsAdmin />);

    const fila = await screen.findByRole("row", { name: /Dra. Ficticia Uno/ });
    expect(within(fila).getByText("Activo")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /Dr. Inactivo/ })).toHaveTextContent("Inactivo");
    expect(screen.queryByRole("button", { name: /Eliminar|Borrar/ })).not.toBeInTheDocument();
  });

  it("alta con color y buffer", async () => {
    let enviado: unknown = null;
    server.use(
      http.post("/api/professionals", async ({ request }) => {
        enviado = await request.json();
        return HttpResponse.json(professional({ id: "prof-9" }), { status: 201 });
      }),
      ...agendaHandlers()
    );
    const { user } = await render(<ProfessionalsAdmin />);

    await user.click(await screen.findByRole("button", { name: "Nuevo profesional" }));
    await user.type(screen.getByLabelText("Nombre"), "Dr. Ficticio Nuevo");
    await user.clear(screen.getByLabelText("Color"));
    await user.type(screen.getByLabelText("Color"), "#123abc");
    await user.clear(screen.getByLabelText("Buffer (min)"));
    await user.type(screen.getByLabelText("Buffer (min)"), "10");
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    await waitFor(() =>
      expect(enviado).toEqual({
        display_name: "Dr. Ficticio Nuevo",
        color: "#123abc",
        default_duration_min: 30,
        buffer_min: 10,
        booking_enabled: true
      })
    );
  });

  it("desactivar y reactivar", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      http.patch("/api/professionals/prof-1", async ({ request }) => {
        cuerpos.push(await request.json());
        return HttpResponse.json(professional({ active: false }));
      }),
      ...agendaHandlers()
    );
    const { user } = await render(<ProfessionalsAdmin />);

    await user.click(await screen.findByRole("button", { name: "Desactivar Dra. Ficticia Uno" }));

    await waitFor(() => expect(cuerpos).toEqual([{ active: false }]));
  });

  it("edita solo lo que cambió y muestra errores de la API", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      http.patch("/api/professionals/prof-1", async ({ request }) => {
        cuerpos.push(await request.json());
        return HttpResponse.json({ detail: [{ loc: ["body"] }] }, { status: 422 });
      }),
      ...agendaHandlers()
    );
    const { user } = await render(<ProfessionalsAdmin />);

    await user.click(await screen.findByRole("button", { name: "Editar Dra. Ficticia Uno" }));
    await user.clear(screen.getByLabelText("Duración por defecto (min)"));
    await user.type(screen.getByLabelText("Duración por defecto (min)"), "45");
    await user.click(screen.getByRole("button", { name: "Guardar" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Revisá los datos ingresados");
    expect(cuerpos).toEqual([{ default_duration_min: 45 }]);
  });
});

describe("ChairsAdmin", () => {
  it("alta y desactivación de sillones", async () => {
    const altas: unknown[] = [];
    const cambios: unknown[] = [];
    server.use(
      http.post("/api/chairs", async ({ request }) => {
        altas.push(await request.json());
        return HttpResponse.json(chair({ id: "chair-9", name: "Sillón 9" }), { status: 201 });
      }),
      http.patch("/api/chairs/chair-1", async ({ request }) => {
        cambios.push(await request.json());
        return HttpResponse.json(chair({ active: false }));
      }),
      ...agendaHandlers()
    );
    const { user } = await render(<ChairsAdmin />);

    expect(await screen.findByRole("row", { name: /Sillón 1/ })).toHaveTextContent("Activo");
    await user.click(screen.getByRole("button", { name: "Nuevo sillón" }));
    await user.type(screen.getByLabelText("Nombre"), "Sillón 9");
    await user.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(altas).toEqual([{ name: "Sillón 9" }]));

    await user.click(screen.getByRole("button", { name: "Desactivar Sillón 1" }));
    await waitFor(() => expect(cambios).toEqual([{ active: false }]));
  });
});
