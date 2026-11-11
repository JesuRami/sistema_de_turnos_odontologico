/**
 * Pestañas Anamnesis, Adjuntos y Presupuestos de la historia clínica (C-15). Todo el estado vive
 * en memoria del componente (D11): nada en `localStorage`/`sessionStorage` ni en la cola offline.
 */
import { useEffect, useState } from "react";
import { ApiError } from "../../shared/api/client";
import {
  createPlan,
  downloadAttachment,
  listAttachments,
  listPlans,
  planPdf,
  removeAttachment,
  saveAnamnesis,
  uploadAttachment
} from "./api";
import type { Anamnesis, AnamnesisAnswers, Attachment, AttachmentKind, PlanSummary } from "./types";

/** Espejo provisorio de `SYSTEMIC_CONDITIONS` (backend `clinical/catalog.py`, Decisión 9). */
export const SYSTEMIC_CONDITIONS: ReadonlyArray<readonly [string, string]> = [
  ["hipertension", "Hipertensión"],
  ["diabetes", "Diabetes"],
  ["cardiopatia", "Cardiopatía"],
  ["asma", "Asma"],
  ["hepatitis", "Hepatitis"],
  ["vih", "VIH"],
  ["trastorno_coagulacion", "Trastorno de la coagulación"],
  ["enfermedad_renal", "Enfermedad renal"],
  ["epilepsia", "Epilepsia"],
  ["tiroides", "Trastorno tiroideo"]
];

export const MAX_FILE_BYTES = 10 * 1024 * 1024;
const TIPOS_PERMITIDOS = new Set(["image/jpeg", "image/png", "application/pdf"]);

/** Mensajes sin texto clínico (solo el código del error). */
export function mensajeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail === "patient_archived") return "El paciente está archivado: solo lectura.";
    if (error.detail === "version_conflict") return "Versión desactualizada: recargá la vigente.";
    return `No se pudo guardar (${error.detail}).`;
  }
  return "No se pudo guardar: revisá la conexión e intentá de nuevo.";
}

const pesos = new Intl.NumberFormat("es-AR", { style: "currency", currency: "ARS" });
export function formatCents(cents: number): string {
  return pesos.format(cents / 100);
}

function lista(texto: string): string[] {
  return texto
    .split(",")
    .map((t) => t.trim())
    .filter((t) => t !== "");
}

function abrirBlob(blob: Blob): void {
  const url = URL.createObjectURL(blob);
  window.open(url, "_blank", "noopener");
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export function AnamnesisTab({
  recordId,
  current,
  onSaved
}: {
  recordId: string;
  current: Anamnesis | null;
  onSaved: () => void;
}): JSX.Element {
  const previo = (current?.answers ?? {}) as Partial<AnamnesisAnswers>;
  const [alergias, setAlergias] = useState((previo.allergies ?? []).join(", "));
  const [medicacion, setMedicacion] = useState((previo.medications ?? []).join(", "));
  const [sistemicas, setSistemicas] = useState<string[]>(previo.systemic_conditions ?? []);
  const [embarazo, setEmbarazo] = useState<boolean | null>(previo.pregnant ?? null);
  const [fuma, setFuma] = useState(previo.smoker ?? false);
  const [anticoag, setAnticoag] = useState(previo.anticoagulants ?? false);
  const [obs, setObs] = useState(previo.observations ?? "");
  const [error, setError] = useState<string | null>(null);

  async function guardar(): Promise<void> {
    setError(null);
    try {
      await saveAnamnesis(recordId, current?.version ?? 0, {
        allergies: lista(alergias),
        medications: lista(medicacion),
        systemic_conditions: sistemicas,
        pregnant: embarazo,
        smoker: fuma,
        anticoagulants: anticoag,
        observations: obs
      });
      onSaved();
    } catch (fallo) {
      // Lo escrito queda en el formulario (memoria); no se encola ningún reintento.
      setError(mensajeError(fallo));
    }
  }

  return (
    <section aria-label="Anamnesis" className="space-y-2 text-sm">
      <p className="text-slate-600">
        {current ? `Versión vigente: ${current.version}` : "Sin anamnesis cargada"}
      </p>
      <label className="block">
        Alergias (separadas por coma)
        <input value={alergias} onChange={(e) => setAlergias(e.target.value)} className="block w-full rounded border p-1" />
      </label>
      <label className="block">
        Medicación (separada por coma)
        <input value={medicacion} onChange={(e) => setMedicacion(e.target.value)} className="block w-full rounded border p-1" />
      </label>
      <fieldset className="grid grid-cols-2 gap-1">
        <legend>Condiciones sistémicas</legend>
        {SYSTEMIC_CONDITIONS.map(([code, label]) => (
          <label key={code} className="flex items-center gap-1">
            <input
              type="checkbox"
              checked={sistemicas.includes(code)}
              onChange={(e) =>
                setSistemicas((prev) =>
                  e.target.checked ? [...prev, code] : prev.filter((c) => c !== code)
                )
              }
            />
            {label}
          </label>
        ))}
      </fieldset>
      <label className="block">
        Embarazo
        <select
          value={embarazo === null ? "" : String(embarazo)}
          onChange={(e) => setEmbarazo(e.target.value === "" ? null : e.target.value === "true")}
          className="ml-2 rounded border p-1"
        >
          <option value="">No corresponde</option>
          <option value="true">Sí</option>
          <option value="false">No</option>
        </select>
      </label>
      <label className="flex items-center gap-1">
        <input type="checkbox" checked={fuma} onChange={(e) => setFuma(e.target.checked)} />
        Tabaquismo
      </label>
      <label className="flex items-center gap-1">
        <input type="checkbox" checked={anticoag} onChange={(e) => setAnticoag(e.target.checked)} />
        Anticoagulantes
      </label>
      <label className="block">
        Observaciones
        <textarea
          value={obs}
          maxLength={1000}
          onChange={(e) => setObs(e.target.value)}
          className="block w-full rounded border p-2"
        />
      </label>
      {error ? <p role="alert">{error}</p> : null}
      <button type="button" onClick={() => void guardar()} className="rounded border px-3 py-1">
        Guardar anamnesis
      </button>
    </section>
  );
}

export function AttachmentsTab({ recordId }: { recordId: string }): JSX.Element {
  const [items, setItems] = useState<Attachment[]>([]);
  const [tipo, setTipo] = useState<AttachmentKind>("xray");
  const [error, setError] = useState<string | null>(null);

  async function cargar(): Promise<void> {
    setItems((await listAttachments(recordId)).items);
  }
  useEffect(() => {
    void listAttachments(recordId).then((p) => setItems(p.items));
  }, [recordId]);

  async function subir(file: File | undefined): Promise<void> {
    setError(null);
    if (!file) return;
    if (!TIPOS_PERMITIDOS.has(file.type)) {
      setError("Solo se aceptan archivos JPG, PNG o PDF.");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError("El archivo supera el máximo de 10 MB.");
      return;
    }
    try {
      await uploadAttachment(recordId, file, tipo);
      await cargar();
    } catch (fallo) {
      setError(mensajeError(fallo));
    }
  }

  async function quitar(id: string): Promise<void> {
    const motivo = window.prompt("Motivo de la baja (obligatorio)")?.trim();
    if (!motivo) return;
    try {
      await removeAttachment(recordId, id, motivo);
      await cargar();
    } catch (fallo) {
      setError(mensajeError(fallo));
    }
  }

  return (
    <section aria-label="Adjuntos" className="space-y-2 text-sm">
      <div className="flex items-center gap-2">
        <select value={tipo} onChange={(e) => setTipo(e.target.value as AttachmentKind)} aria-label="Tipo de adjunto" className="rounded border p-1">
          <option value="xray">Radiografía</option>
          <option value="photo">Foto</option>
          <option value="document">Documento</option>
        </select>
        <label>
          Archivo
          <input
            type="file"
            accept="image/jpeg,image/png,application/pdf"
            onChange={(e) => {
              void subir(e.target.files?.[0]);
              e.target.value = "";
            }}
            className="ml-2"
          />
        </label>
      </div>
      {error ? <p role="alert">{error}</p> : null}
      <ul className="space-y-1">
        {items.map((a) => (
          <li key={a.id} className="flex items-center gap-2 rounded border p-2">
            <span className={a.removed ? "line-through" : ""}>{a.display_name}</span>
            <span className="text-xs text-slate-500">{Math.ceil(a.size_bytes / 1024)} KB</span>
            {a.removed ? (
              <span className="text-xs">Dado de baja</span>
            ) : (
              <>
                <button type="button" onClick={() => void downloadAttachment(recordId, a.id).then(abrirBlob)}>
                  Ver
                </button>
                <button type="button" onClick={() => void quitar(a.id)}>
                  Dar de baja
                </button>
              </>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function PlansTab({ recordId }: { recordId: string }): JSX.Element {
  const [items, setItems] = useState<PlanSummary[]>([]);
  const [titulo, setTitulo] = useState("");
  const [descripcion, setDescripcion] = useState("");
  const [precio, setPrecio] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function cargar(): Promise<void> {
    setItems((await listPlans(recordId)).items);
  }
  useEffect(() => {
    void listPlans(recordId).then((p) => setItems(p.items));
  }, [recordId]);

  async function crear(): Promise<void> {
    setError(null);
    const cents = Math.round(Number(precio.replace(",", ".")) * 100);
    if (!Number.isFinite(cents) || cents < 0) {
      setError("Precio inválido.");
      return;
    }
    try {
      // Los totales los calcula el servidor; la UI solo envía ítems.
      await createPlan(recordId, titulo, [
        { phase: 1, description: descripcion, quantity: 1, unit_price_cents: cents }
      ]);
      setTitulo("");
      setDescripcion("");
      setPrecio("");
      await cargar();
    } catch (fallo) {
      setError(mensajeError(fallo));
    }
  }

  return (
    <section aria-label="Presupuestos" className="space-y-2 text-sm">
      <ul className="space-y-1">
        {items.map((p) => (
          <li key={p.id} className="flex items-center gap-2 rounded border p-2">
            <span>{p.title}</span>
            <span>{formatCents(p.total_cents)}</span>
            <span className="text-xs text-slate-500">
              v{p.latest_version}
              {p.decision === "accepted" ? " · Aceptado" : p.decision === "rejected" ? " · Rechazado" : ""}
            </span>
            <button type="button" onClick={() => void planPdf(recordId, p.id, p.latest_version).then(abrirBlob)}>
              PDF
            </button>
          </li>
        ))}
      </ul>
      <fieldset className="space-y-1">
        <legend>Nuevo presupuesto (una fase)</legend>
        <input aria-label="Título" placeholder="Título" value={titulo} onChange={(e) => setTitulo(e.target.value)} className="block rounded border p-1" />
        <input aria-label="Prestación" placeholder="Prestación" value={descripcion} onChange={(e) => setDescripcion(e.target.value)} className="block rounded border p-1" />
        <input aria-label="Precio" placeholder="Precio" inputMode="decimal" value={precio} onChange={(e) => setPrecio(e.target.value)} className="block rounded border p-1" />
      </fieldset>
      {error ? <p role="alert">{error}</p> : null}
      <button
        type="button"
        disabled={titulo.trim().length < 3 || descripcion.trim() === "" || precio === ""}
        onClick={() => void crear()}
        className="rounded border px-3 py-1 disabled:opacity-50"
      >
        Crear presupuesto
      </button>
    </section>
  );
}
