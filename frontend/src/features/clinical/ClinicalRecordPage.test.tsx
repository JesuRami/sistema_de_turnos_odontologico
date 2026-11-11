/**
 * C-15 (web/clinical-record): pestañas Anamnesis, Adjuntos y Presupuestos, corrección de
 * evoluciones solo del autor y ningún dato clínico en almacenamiento del navegador.
 * Datos sintéticos (regla 13).
 */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import ClinicalRecordPage from "./ClinicalRecordPage";
import type { ClinicalRecord, Evolution } from "./types";

const REC = "rec-1";
const BASE = `/api/clinical-records/${REC}`;

const ficha: ClinicalRecord = {
  record_id: REC,
  patient_id: "pat-1",
  patient_name: "Paciente Ficticio",
  patient_archived: false,
  created_at: "2030-01-07T13:00:00Z",
  anamnesis: null,
  evolutions_count: 1,
  attachments_count: 0,
  plans_count: 0
};

function evolucion(autor: string): Evolution {
  return {
    id: "evo-1",
    record_id: REC,
    kind: "entry",
    body: "Control de rutina ficticio",
    appointment_id: null,
    professional_id: "prof-1",
    created_by_user_id: autor,
    signed_at: "2030-01-07T13:05:00Z",
    content_sha256: "0".repeat(64),
    corrects_evolution_id: null,
    reason: null,
    corrected_by: null
  };
}

async function abrir(pestana?: RegExp, userId = "user-odontologo") {
  renderWithProviders(
    <Routes>
      <Route path="/pacientes/:patientId/historia-clinica" element={<ClinicalRecordPage />} />
    </Routes>,
    {
      route: "/pacientes/pat-1/historia-clinica",
      session: await loggedSession(makeUser("odontologo", { id: userId }))
    }
  );
  await screen.findByText(/Historia clínica · Paciente Ficticio/);
  if (pestana) await userEvent.click(screen.getByRole("tab", { name: pestana }));
}

beforeEach(() => {
  server.use(
    http.get("/api/patients/pat-1/clinical-record", () => HttpResponse.json(ficha)),
    http.get("/api/odontogram/conditions", () => HttpResponse.json({ items: [] })),
    http.get(`${BASE}/odontogram`, () => HttpResponse.json({ dentition: "permanent", teeth: [] })),
    http.get(`${BASE}/evolutions`, () =>
      HttpResponse.json({ items: [evolucion("user-odontologo")], next_cursor: null })
    ),
    http.get(`${BASE}/attachments`, () => HttpResponse.json({ items: [], next_cursor: null })),
    http.get(`${BASE}/treatment-plans`, () => HttpResponse.json({ items: [], next_cursor: null }))
  );
});

afterEach(() => vi.restoreAllMocks());

describe("Anamnesis", () => {
  it("guarda con expected_version y ante conflicto conserva lo escrito", async () => {
    const cuerpos: unknown[] = [];
    server.use(
      http.post(`${BASE}/anamnesis`, async ({ request }) => {
        cuerpos.push(await request.json());
        return HttpResponse.json({ detail: "version_conflict" }, { status: 409 });
      })
    );
    await abrir(/anamnesis/i);
    await userEvent.click(screen.getByRole("checkbox", { name: "Diabetes" }));
    await userEvent.type(screen.getByLabelText(/Observaciones/), "Nota ficticia");
    await userEvent.click(screen.getByRole("button", { name: /Guardar anamnesis/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Versión desactualizada");
    expect(cuerpos[0]).toMatchObject({
      expected_version: 0,
      answers: { systemic_conditions: ["diabetes"], observations: "Nota ficticia" }
    });
    expect(screen.getByLabelText(/Observaciones/)).toHaveValue("Nota ficticia");
  });
});

describe("Adjuntos", () => {
  it("rechaza en el navegador un archivo de tipo o tamaño inválido sin subirlo", async () => {
    let subidas = 0;
    server.use(
      http.post(`${BASE}/attachments`, () => {
        subidas += 1;
        return HttpResponse.json({}, { status: 201 });
      })
    );
    await abrir(/adjuntos/i);
    const input = screen.getByLabelText(/Archivo/);
    fireEvent.change(input, {
      target: { files: [new File(["x"], "nota.txt", { type: "text/plain" })] }
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("JPG, PNG o PDF");

    const grande = new File([new Uint8Array(10 * 1024 * 1024 + 1)], "rx.png", { type: "image/png" });
    fireEvent.change(input, { target: { files: [grande] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("10 MB");
    expect(subidas).toBe(0);
  });
});

describe("Presupuestos", () => {
  it("muestra los totales que calcula el servidor", async () => {
    server.use(
      http.get(`${BASE}/treatment-plans`, () =>
        HttpResponse.json({
          items: [
            {
              id: "plan-1",
              title: "Plan ficticio",
              created_at: "2030-01-07T13:00:00Z",
              latest_version: 1,
              total_cents: 1234500,
              decision: null
            }
          ],
          next_cursor: null
        })
      )
    );
    await abrir(/presupuestos/i);
    expect(await screen.findByText("Plan ficticio")).toBeInTheDocument();
    expect(screen.getByText(/12\.345,00/)).toBeInTheDocument();
  });
});

describe("Corrección de evoluciones", () => {
  it("solo el autor ve el botón Corregir", async () => {
    await abrir(/evoluciones/i);
    expect(await screen.findByRole("button", { name: /Corregir/ })).toBeInTheDocument();
  });

  it("otro profesional no puede corregir", async () => {
    await abrir(/evoluciones/i, "user-otro");
    await screen.findByText("Control de rutina ficticio");
    expect(screen.queryByRole("button", { name: /Corregir/ })).not.toBeInTheDocument();
  });
});

describe("Almacenamiento del navegador", () => {
  it("ningún dato clínico se escribe en localStorage ni sessionStorage", async () => {
    const local = vi.spyOn(Storage.prototype, "setItem");
    await abrir(/anamnesis/i);
    await userEvent.type(screen.getByLabelText(/Observaciones/), "Dato ficticio");
    await waitFor(() => expect(screen.getByLabelText(/Observaciones/)).toHaveValue("Dato ficticio"));
    const escritos = local.mock.calls.map(([, v]) => String(v)).join(" ");
    expect(escritos).not.toContain("Dato ficticio");
    expect(escritos).not.toContain("Paciente Ficticio");
  });
});
