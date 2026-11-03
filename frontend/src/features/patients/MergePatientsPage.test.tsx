import { screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { Patient, PatientDetail } from "../../shared/api/types";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import MergePatientsPage from "./MergePatientsPage";

const CONSERVADA: PatientDetail = {
  id: "pat-1",
  full_name: "Ana Prueba Ejemplo",
  phone_e164: "+5491155550001",
  email: null,
  dni: null,
  whatsapp_opt_in: true,
  archived_at: null,
  merged_into_patient_id: null,
  appointments_count: 4
};
const DUPLICADA: PatientDetail = {
  ...CONSERVADA,
  id: "pat-2",
  full_name: "ANA PRUEBA EJEMPLO",
  email: "ana.prueba@example.com",
  whatsapp_opt_in: false,
  appointments_count: 2
};

function handlers() {
  const lista: Patient[] = [CONSERVADA, DUPLICADA];
  return [
    http.get("/api/patients", () => HttpResponse.json({ items: lista })),
    http.get("/api/patients/pat-1", () => HttpResponse.json(CONSERVADA)),
    http.get("/api/patients/pat-2", () => HttpResponse.json(DUPLICADA))
  ];
}

async function elegirAmbas() {
  const r = renderWithProviders(<MergePatientsPage />, {
    session: await loggedSession(makeUser("recepcion"))
  });
  const { user } = r;
  await user.type(screen.getByLabelText("Buscar la ficha que se conserva"), "ana prueba");
  await user.click(await screen.findByRole("button", { name: "Elegir Ana Prueba Ejemplo" }));
  await user.type(await screen.findByLabelText("Buscar la ficha duplicada"), "ana prueba");
  await user.click(await screen.findByRole("button", { name: "Elegir ANA PRUEBA EJEMPLO" }));
  return r;
}

describe("MergePatientsPage", () => {
  it("muestra ambas fichas y los turnos que se mueven, y exige confirmar", async () => {
    server.use(...handlers());
    await elegirAmbas();

    const conservada = await screen.findByRole("region", { name: "Ficha que se conserva" });
    const duplicada = screen.getByRole("region", { name: "Ficha duplicada" });
    expect(within(conservada).getByText("Ana Prueba Ejemplo")).toBeInTheDocument();
    expect(within(duplicada).getByText("ana.prueba@example.com")).toBeInTheDocument();
    expect(screen.getByText(/^La fusión no se puede deshacer./)).toHaveTextContent("2 turnos");
    expect(screen.getByRole("button", { name: "Fusionar fichas" })).toBeDisabled();
  });

  it("fusiona y muestra el resultado", async () => {
    let enviado: unknown = null;
    server.use(
      http.post("/api/patients/pat-2/merge", async ({ request }) => {
        enviado = await request.json();
        return HttpResponse.json({
          merge_id: "m-1",
          source_patient_id: "pat-2",
          target_patient_id: "pat-1",
          moved_appointments: 2,
          appointment_ids: ["a", "b"],
          filled_fields: ["email"]
        });
      }),
      ...handlers()
    );
    const { user } = await elegirAmbas();

    await user.click(await screen.findByLabelText("Entiendo que la fusión no se puede deshacer"));
    await user.click(screen.getByRole("button", { name: "Fusionar fichas" }));

    expect(await screen.findByText("Fusión completada: 2 turnos movidos. Se completó: email.")).toBeInTheDocument();
    expect(enviado).toEqual({ into_patient_id: "pat-1" });
  });

  it("si la API rechaza la fusión muestra el motivo", async () => {
    server.use(
      http.post("/api/patients/pat-2/merge", () =>
        HttpResponse.json({ detail: "invalid_merge" }, { status: 422 })
      ),
      ...handlers()
    );
    const { user } = await elegirAmbas();

    await user.click(await screen.findByLabelText("Entiendo que la fusión no se puede deshacer"));
    await user.click(screen.getByRole("button", { name: "Fusionar fichas" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("No se pueden fusionar esas fichas");
    await waitFor(() => expect(screen.queryByText(/Fusión completada/)).not.toBeInTheDocument());
  });
});
