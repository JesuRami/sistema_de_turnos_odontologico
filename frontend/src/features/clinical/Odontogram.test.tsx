import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import App from "../../App";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import { saveOdontogram } from "./api";
import { DECIDUOUS_TEETH, PERMANENT_TEETH, chunk, surfaceLabel, type Surface } from "./fdi";
import Odontogram, { draftKey, type Draft } from "./Odontogram";
import type { Condition, OdontogramEntry } from "./types";

const CARIES: Condition = {
  id: "c-caries",
  code: "caries",
  label: "Caries",
  category: "patologia",
  scope: "surface",
  active: true
};

function Harness(): JSX.Element {
  const [draft, setDraft] = useState<Draft>(new Map());
  return (
    <>
      <Odontogram
        dentition="permanent"
        teeth={[]}
        conditions={[CARIES]}
        draft={draft}
        onDraft={(t: number, s: Surface, id: string | null) =>
          setDraft((prev) => new Map(prev).set(draftKey(t, s), id))
        }
      />
      <output data-testid="draft">{JSON.stringify([...draft])}</output>
    </>
  );
}

describe("FDI", () => {
  it("32 permanentes, 20 temporales y caras con incisal en anteriores", () => {
    expect(PERMANENT_TEETH).toHaveLength(32);
    expect(DECIDUOUS_TEETH).toHaveLength(20);
    expect(DECIDUOUS_TEETH[0]).toBe(51);
    expect(surfaceLabel(36, "O")).toBe("oclusal");
    expect(surfaceLabel(11, "O")).toBe("incisal");
    expect(chunk(Array.from({ length: 33 }, (_, i) => i), 32).map((p) => p.length)).toEqual([32, 1]);
  });
});

describe("Odontogram", () => {
  it("marca 36/O con teclado, la etiqueta accesible lo anuncia y queda en el borrador", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    expect(screen.getAllByRole("row")).toHaveLength(32);
    expect(screen.getAllByRole("gridcell")).toHaveLength(32 * 6);

    const primera = screen.getByRole("gridcell", { name: "Pieza 11, cara mesial: sin hallazgos" });
    primera.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("gridcell", { name: "Pieza 11, cara distal: sin hallazgos" })).toHaveFocus();

    await user.click(screen.getByRole("gridcell", { name: "Pieza 36, cara oclusal: sin hallazgos" }));
    await user.selectOptions(screen.getByLabelText("Estado para pieza 36, cara oclusal"), "Caries");

    const marcada = screen.getByRole("gridcell", { name: "Pieza 36, cara oclusal: caries" });
    expect(marcada).toHaveTextContent("·CAR");
    expect(screen.getByTestId("draft")).toHaveTextContent('[["36-O","c-caries"]]');
  });

  it("guarda 33 cambios en dos lotes y conserva los no confirmados si uno falla", async () => {
    const lotes: number[] = [];
    server.use(
      http.post("/api/clinical-records/r1/odontogram/events", async ({ request }) => {
        const cuerpo = (await request.json()) as { entries: OdontogramEntry[] };
        lotes.push(cuerpo.entries.length);
        return lotes.length === 1
          ? HttpResponse.json({ items: [] }, { status: 201 })
          : HttpResponse.json({ detail: "condition_inactive" }, { status: 422 });
      })
    );
    const entradas: OdontogramEntry[] = Array.from({ length: 33 }, (_, i) => ({
      tooth: PERMANENT_TEETH[i % 32],
      surface: i < 32 ? "O" : "M",
      condition_id: null
    }));

    const { pending, error } = await saveOdontogram("r1", entradas);

    expect(lotes).toEqual([32, 1]);
    expect(pending).toHaveLength(1);
    expect(error).not.toBeNull();
  });
});

describe("Ruta de la historia clínica", () => {
  it("recepción ve el aviso sin permiso y no se pide nada clínico", async () => {
    const clinicas: string[] = [];
    server.events.on("request:start", ({ request }) => {
      if (request.url.includes("clinical")) clinicas.push(request.url);
    });
    renderWithProviders(<App />, {
      route: "/pacientes/pat-1/historia-clinica",
      session: await loggedSession(makeUser("recepcion"))
    });

    expect(await screen.findByText("No tenés permiso para esta sección")).toBeInTheDocument();
    expect(clinicas).toEqual([]);
    expect(JSON.stringify({ ...localStorage })).not.toContain("clinical");
  });
});
