/**
 * Historia clínica del paciente (C-15, web/clinical-record). Solo admin y odontólogo (la ruta va
 * envuelta en `RequireRole`; la seguridad real es del backend). Todo el estado clínico vive en
 * memoria del componente: nada en `localStorage`/`sessionStorage`/cola offline, y se descarta al
 * cambiar de paciente (la vista se monta con `key={patientId}`).
 */
import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError } from "../../shared/api/client";
import { useAuth } from "../../shared/auth/AuthProvider";
import {
  createCorrection,
  createEvolution,
  getConditions,
  getOdontogram,
  getRecord,
  listEvolutions,
  openRecord,
  saveOdontogram
} from "./api";
import type { Dentition, Surface } from "./fdi";
import { AnamnesisTab, AttachmentsTab, mensajeError as mensaje, PlansTab } from "./ClinicalTabs";
import Odontogram, { draftEntries, draftKey } from "./Odontogram";
import type { ClinicalRecord, Condition, Evolution, OdontogramState } from "./types";

type Pestana = "odontograma" | "evoluciones" | "anamnesis" | "adjuntos" | "presupuestos";
const PESTANAS: readonly Pestana[] = ["odontograma", "evoluciones", "anamnesis", "adjuntos", "presupuestos"];

type Estado =
  | { tipo: "cargando" }
  | { tipo: "sin_ficha" }
  | { tipo: "no_encontrado" }
  | { tipo: "error" }
  | { tipo: "ok"; ficha: ClinicalRecord };

function OdontogramTab({ recordId }: { recordId: string }): JSX.Element {
  const [dentition, setDentition] = useState<Dentition>("permanent");
  const [estado, setEstado] = useState<OdontogramState | null>(null);
  const [condiciones, setCondiciones] = useState<Condition[]>([]);
  const [draft, setDraft] = useState<Map<string, string | null>>(new Map());
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async () => {
    setEstado(await getOdontogram(recordId, dentition));
  }, [recordId, dentition]);

  useEffect(() => {
    void cargar();
  }, [cargar]);
  useEffect(() => {
    void getConditions().then((r) => setCondiciones(r.items));
  }, []);

  async function guardar(): Promise<void> {
    setError(null);
    const { pending, error: fallo } = await saveOdontogram(recordId, draftEntries(draft));
    setDraft(new Map(pending.map((e) => [draftKey(e.tooth, e.surface), e.condition_id])));
    if (fallo) setError(mensaje(fallo));
    await cargar();
  }

  return (
    <section aria-label="Odontograma">
      <div className="mb-2 flex gap-2">
        {(["permanent", "deciduous"] as const).map((d) => (
          <button
            key={d}
            type="button"
            aria-pressed={dentition === d}
            onClick={() => setDentition(d)}
            className="rounded border px-2 py-1 text-sm"
          >
            {d === "permanent" ? "Permanente" : "Temporal"}
          </button>
        ))}
      </div>
      {estado ? (
        <Odontogram
          dentition={dentition}
          teeth={estado.teeth}
          conditions={condiciones}
          draft={draft}
          onDraft={(tooth: number, surface: Surface, id: string | null) =>
            setDraft((prev) => new Map(prev).set(draftKey(tooth, surface), id))
          }
        />
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
      <button
        type="button"
        disabled={draft.size === 0}
        onClick={() => void guardar()}
        className="mt-3 rounded bg-slate-800 px-3 py-1 text-white disabled:opacity-50"
      >
        Guardar ({draft.size})
      </button>
    </section>
  );
}

function EvolutionsTab({ recordId }: { recordId: string }): JSX.Element {
  const userId = useAuth().user?.id ?? null;
  const [items, setItems] = useState<Evolution[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [texto, setTexto] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void listEvolutions(recordId).then((p) => {
      setItems(p.items);
      setCursor(p.next_cursor);
    });
  }, [recordId]);

  async function crear(): Promise<void> {
    setError(null);
    try {
      const creada = await createEvolution(recordId, texto);
      setItems((prev) => [creada, ...prev]);
      setTexto("");
    } catch (fallo) {
      // El texto queda en el formulario (memoria); no se encola ningún reintento.
      setError(mensaje(fallo));
    }
  }

  async function corregir(original: Evolution): Promise<void> {
    const motivo = window.prompt("Motivo de la corrección (obligatorio)")?.trim();
    if (!motivo) return;
    const cuerpo = window.prompt("Texto corregido", original.body)?.trim();
    if (!cuerpo) return;
    setError(null);
    try {
      const nueva = await createCorrection(recordId, original.id, motivo, cuerpo);
      setItems((prev) => [
        nueva,
        ...prev.map((e) => (e.id === original.id ? { ...e, corrected_by: nueva.id } : e))
      ]);
    } catch (fallo) {
      setError(mensaje(fallo));
    }
  }

  async function masItems(siguiente: string): Promise<void> {
    const p = await listEvolutions(recordId, siguiente);
    setItems((prev) => [...prev, ...p.items]);
    setCursor(p.next_cursor);
  }

  return (
    <section aria-label="Evoluciones">
      <label className="block text-sm">
        Nueva evolución (firma simple)
        <textarea
          value={texto}
          maxLength={4000}
          onChange={(e) => setTexto(e.target.value)}
          className="mt-1 block w-full rounded border p-2"
        />
      </label>
      {error ? <p role="alert">{error}</p> : null}
      <button
        type="button"
        disabled={texto.trim() === ""}
        onClick={() => void crear()}
        className="mt-2 rounded border px-3 py-1"
      >
        Guardar evolución
      </button>
      <ul className="mt-3 space-y-2">
        {items.map((e) => (
          <li key={e.id} className="rounded border p-2 text-sm">
            <p className="whitespace-pre-wrap">{e.body}</p>
            <p className="text-xs text-slate-500">
              {new Date(e.signed_at).toLocaleString("es-AR")}
              {e.kind === "correction" ? " · Corrección" : ""}
              {e.corrected_by ? " · Corregida" : ""}
            </p>
            {e.created_by_user_id === userId && e.kind === "entry" && !e.corrected_by ? (
              <button type="button" onClick={() => void corregir(e)} className="text-xs underline">
                Corregir
              </button>
            ) : null}
          </li>
        ))}
      </ul>
      {cursor ? (
        <button type="button" onClick={() => void masItems(cursor)}>
          Cargar más
        </button>
      ) : null}
    </section>
  );
}

function RecordView({ patientId }: { patientId: string }): JSX.Element {
  const [estado, setEstado] = useState<Estado>({ tipo: "cargando" });
  const [pestana, setPestana] = useState<Pestana>("odontograma");

  const cargar = useCallback(async () => {
    try {
      setEstado({ tipo: "ok", ficha: await getRecord(patientId) });
    } catch (error) {
      if (error instanceof ApiError && error.detail === "clinical_record_not_opened") {
        setEstado({ tipo: "sin_ficha" });
      } else if (error instanceof ApiError && error.status === 404) {
        setEstado({ tipo: "no_encontrado" });
      } else {
        setEstado({ tipo: "error" });
      }
    }
  }, [patientId]);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  if (estado.tipo === "cargando") return <p className="p-6">Cargando…</p>;
  if (estado.tipo === "no_encontrado") return <p className="p-6">Paciente no encontrado</p>;
  if (estado.tipo === "error") {
    return (
      <p role="alert" className="p-6">
        No se pudo cargar la historia clínica.
      </p>
    );
  }
  if (estado.tipo === "sin_ficha") {
    return (
      <section className="p-6">
        <p>Este paciente todavía no tiene historia clínica.</p>
        <button
          type="button"
          className="mt-2 rounded border px-3 py-1"
          onClick={() => void openRecord(patientId).then(cargar)}
        >
          Abrir historia clínica
        </button>
      </section>
    );
  }
  const { ficha } = estado;
  return (
    <section className="p-6">
      <h1 className="text-lg font-semibold">Historia clínica · {ficha.patient_name}</h1>
      <p className="text-sm text-slate-600">
        Anamnesis: {ficha.anamnesis ? `versión ${ficha.anamnesis.version}` : "sin cargar"} ·
        Evoluciones: {ficha.evolutions_count} · Adjuntos: {ficha.attachments_count} ·
        Presupuestos: {ficha.plans_count}
      </p>
      <div role="tablist" className="my-3 flex gap-2">
        {PESTANAS.map((t) => (
          <button
            key={t}
            role="tab"
            type="button"
            aria-selected={pestana === t}
            onClick={() => setPestana(t)}
            className="rounded border px-2 py-1 text-sm capitalize"
          >
            {t}
          </button>
        ))}
      </div>
      {pestana === "odontograma" ? <OdontogramTab recordId={ficha.record_id} /> : null}
      {pestana === "evoluciones" ? <EvolutionsTab recordId={ficha.record_id} /> : null}
      {pestana === "anamnesis" ? (
        <AnamnesisTab recordId={ficha.record_id} current={ficha.anamnesis} onSaved={() => void cargar()} />
      ) : null}
      {pestana === "adjuntos" ? <AttachmentsTab recordId={ficha.record_id} /> : null}
      {pestana === "presupuestos" ? <PlansTab recordId={ficha.record_id} /> : null}
    </section>
  );
}

export default function ClinicalRecordPage(): JSX.Element {
  const { patientId = "" } = useParams();
  return <RecordView key={patientId} patientId={patientId} />;
}
