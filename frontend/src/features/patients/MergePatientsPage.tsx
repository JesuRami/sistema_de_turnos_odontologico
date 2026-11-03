/**
 * Fusión asistida de pacientes duplicados (Flujo 4, caso de error). Se elige la
 * ficha que se conserva y la duplicada, se comparan y se confirma explícitamente:
 * la operación no se deshace. La ficha duplicada queda archivada, nunca borrada.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiFetch } from "../../shared/api/client";
import { messageFor } from "../../shared/api/errors";
import { queryKeys } from "../../shared/api/queries";
import type { PatientDetail, PatientMergeResult } from "../../shared/api/types";
import { Alert, Button, PageTitle } from "../../shared/ui";
import { PatientSearch, type PickedPatient } from "./PatientPicker";

const CAMPO: Record<string, string> = { phone_e164: "teléfono", email: "email", dni: "DNI" };

function useDetail(id: string | null) {
  return useQuery({
    queryKey: ["patient", id],
    queryFn: () => apiFetch<PatientDetail>(`/api/patients/${id ?? ""}`),
    enabled: id !== null
  });
}

function Ficha({ titulo, p }: { titulo: string; p: PatientDetail }): JSX.Element {
  return (
    <section aria-label={titulo} className="flex-1 rounded border border-dental-600/20 bg-white p-3 text-sm">
      <h2 className="mb-2 font-semibold">{titulo}</h2>
      <dl className="space-y-1">
        <dt className="sr-only">Nombre</dt>
        <dd className="font-medium">{p.full_name}</dd>
        <dt className="sr-only">Teléfono</dt>
        <dd>{p.phone_e164 ?? "Sin teléfono"}</dd>
        <dt className="sr-only">Email</dt>
        <dd>{p.email ?? "Sin email"}</dd>
        <dt className="sr-only">DNI</dt>
        <dd>{p.dni ?? "Sin DNI"}</dd>
        <dt className="sr-only">Turnos</dt>
        <dd>{`${p.appointments_count} turno${p.appointments_count === 1 ? "" : "s"}`}</dd>
      </dl>
    </section>
  );
}

function MergePatientsPage(): JSX.Element {
  const queryClient = useQueryClient();
  const [conservada, setConservada] = useState<PickedPatient | null>(null);
  const [duplicada, setDuplicada] = useState<PickedPatient | null>(null);
  const [entiendo, setEntiendo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resultado, setResultado] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);
  const target = useDetail(conservada?.id ?? null);
  const source = useDetail(duplicada?.id ?? null);

  function reiniciar(): void {
    setConservada(null);
    setDuplicada(null);
    setEntiendo(false);
    setError(null);
  }

  async function fusionar(): Promise<void> {
    if (conservada === null || duplicada === null) {
      return;
    }
    setError(null);
    setEnviando(true);
    try {
      const r = await apiFetch<PatientMergeResult>(`/api/patients/${duplicada.id}/merge`, {
        method: "POST",
        body: { into_patient_id: conservada.id }
      });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.appointments }),
        queryClient.invalidateQueries({ queryKey: ["patients"] }),
        queryClient.invalidateQueries({ queryKey: ["patient"] })
      ]);
      const completados = r.filled_fields.map((f) => CAMPO[f] ?? f);
      setResultado(
        `Fusión completada: ${r.moved_appointments} turno${r.moved_appointments === 1 ? "" : "s"} movido${r.moved_appointments === 1 ? "" : "s"}.` +
          (completados.length > 0 ? ` Se completó: ${completados.join(", ")}.` : "")
      );
      reiniciar();
    } catch (e) {
      setError(messageFor(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <section className="space-y-4">
      <PageTitle>Fusionar pacientes</PageTitle>
      {resultado !== null && <Alert tone="success">{resultado}</Alert>}

      <div className="flex flex-col gap-4 md:flex-row">
        <div className="flex-1 space-y-2">
          {conservada === null ? (
            <PatientSearch label="Buscar la ficha que se conserva" onPick={(p) => { setResultado(null); setConservada(p); }} allowCreate={false} />
          ) : target.data !== undefined ? (
            <Ficha titulo="Ficha que se conserva" p={target.data} />
          ) : (
            <p className="text-sm">Cargando ficha…</p>
          )}
        </div>
        <div className="flex-1 space-y-2">
          {conservada !== null &&
            (duplicada === null ? (
              <PatientSearch
                label="Buscar la ficha duplicada"
                onPick={setDuplicada}
                excludeId={conservada.id}
                allowCreate={false}
              />
            ) : source.data !== undefined ? (
              <Ficha titulo="Ficha duplicada" p={source.data} />
            ) : (
              <p className="text-sm">Cargando ficha…</p>
            ))}
        </div>
      </div>

      {target.data !== undefined && source.data !== undefined && (
        <div className="space-y-3 rounded border border-rose-200 bg-rose-50 p-3 text-sm">
          <p>
            {`La fusión no se puede deshacer. Los ${source.data.appointments_count} turnos de la ficha duplicada pasan a la que se conserva, que completa sus datos de contacto vacíos. La ficha duplicada queda archivada.`}
          </p>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={entiendo} onChange={(e) => setEntiendo(e.target.checked)} />
            Entiendo que la fusión no se puede deshacer
          </label>
          <div className="flex gap-2">
            <Button variant="danger" disabled={!entiendo || enviando} onClick={() => void fusionar()}>
              Fusionar fichas
            </Button>
            <Button variant="ghost" onClick={reiniciar}>
              Empezar de nuevo
            </Button>
          </div>
        </div>
      )}
      {error !== null && <Alert>{error}</Alert>}
    </section>
  );
}

export default MergePatientsPage;
