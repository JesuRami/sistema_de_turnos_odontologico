/**
 * Bloqueos y cierres (US-003, RN-BL-01..04). Si un bloqueo pisa turnos, la API
 * responde `409 block_conflicts`: se listan los afectados y admin/recepción
 * pueden cancelarlos en la MISMA operación (RN-BL-02). El sistema nunca los
 * cancela por su cuenta.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, apiFetch } from "../../shared/api/client";
import { messageFor } from "../../shared/api/errors";
import { fetchAll, queryKeys, useChairs, useClinic, useProfessionals } from "../../shared/api/queries";
import type {
  Appointment,
  Block,
  BlockReason,
  CancelInstruction,
  CancellationReason
} from "../../shared/api/types";
import { useAuth } from "../../shared/auth/AuthProvider";
import { useClock } from "../../shared/time/now";
import { dateKeyOf, formatDayLabel, formatTime, fromZonedWallTime } from "../../shared/time/zoned";
import { Alert, Button, Modal, PageTitle, SelectField, TextArea, TextField } from "../../shared/ui";
import { BLOCK_REASON_LABEL, CANCELLATION_REASON_LABEL } from "../agenda/labels";

const MOTIVOS = Object.keys(BLOCK_REASON_LABEL) as BlockReason[];
const MOTIVOS_CANCELACION = Object.keys(CANCELLATION_REASON_LABEL) as CancellationReason[];

interface BlockBody {
  professional_id?: string;
  chair_id?: string;
  starts_at: string;
  ends_at: string;
  reason: BlockReason;
  notes?: string;
  cancel_appointments?: CancelInstruction[];
}

type Envio = { kind: "create"; body: BlockBody } | { kind: "edit"; id: string; body: Partial<BlockBody> };

function BlocksPage(): JSX.Element {
  const queryClient = useQueryClient();
  const clock = useClock();
  const { user } = useAuth();
  const clinic = useClinic();
  const professionals = useProfessionals();
  const chairs = useChairs();
  const tz = clinic.data?.timezone ?? null;
  const [desde] = useState(() => clock().toISOString());
  const vigentes = useQuery({
    queryKey: [...queryKeys.blocks, "vigentes", desde],
    queryFn: () => fetchAll<Block>("/api/blocks", { from: desde }, 200)
  });
  const [form, setForm] = useState<"nuevo" | "cierre" | Block | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const esAdmin = user?.role === "admin";
  const deMostrador = esAdmin || user?.role === "recepcion";

  const nombreProf = new Map((professionals.data ?? []).map((p) => [p.id, p.display_name]));
  const nombreSillon = new Map((chairs.data ?? []).map((c) => [c.id, c.name]));

  const etiqueta = (iso: string): string =>
    tz === null ? iso : `${formatDayLabel(dateKeyOf(new Date(iso), tz))} ${formatTime(new Date(iso), tz)}`;
  const objetivo = (b: Block): string =>
    [b.professional_id !== null ? nombreProf.get(b.professional_id) : undefined, b.chair_id !== null ? nombreSillon.get(b.chair_id) : undefined]
      .filter((x): x is string => x !== undefined)
      .join(" · ") || "—";

  async function refrescar(mensaje: string): Promise<void> {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.blocks }),
      queryClient.invalidateQueries({ queryKey: queryKeys.appointments })
    ]);
    setForm(null);
    setAviso(mensaje);
  }

  async function retirar(b: Block): Promise<void> {
    setError(null);
    try {
      await apiFetch(`/api/blocks/${b.id}`, { method: "DELETE" });
      await refrescar("Bloqueo retirado");
    } catch (e) {
      setError(messageFor(e));
    }
  }

  if (tz === null) {
    return <p className="text-sm">Cargando…</p>;
  }

  return (
    <section>
      <PageTitle
        actions={
          <div className="flex gap-2">
            <Button onClick={() => setForm("nuevo")}>Nuevo bloqueo</Button>
            {esAdmin && (
              <Button variant="secondary" onClick={() => setForm("cierre")}>
                Cierre de clínica
              </Button>
            )}
          </div>
        }
      >
        Bloqueos
      </PageTitle>
      {aviso !== null && (
        <div className="mb-3">
          <Alert tone="success">{aviso}</Alert>
        </div>
      )}
      {error !== null && (
        <div className="mb-3">
          <Alert>{error}</Alert>
        </div>
      )}
      <table className="w-full rounded bg-white text-sm shadow-sm">
        <thead className="bg-dental-50 text-left">
          <tr>
            <th className="px-2 py-1">Motivo</th>
            <th className="px-2 py-1">Objetivo</th>
            <th className="px-2 py-1">Rango</th>
            <th className="px-2 py-1">Notas</th>
            <th className="px-2 py-1">
              <span className="sr-only">Acciones</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {(vigentes.data ?? []).map((b) => (
            <tr key={b.id} className="border-t border-dental-600/10">
              <td className="px-2 py-1">{BLOCK_REASON_LABEL[b.reason]}</td>
              <td className="px-2 py-1">{objetivo(b)}</td>
              <td className="px-2 py-1">{`${etiqueta(b.starts_at)} → ${etiqueta(b.ends_at)}`}</td>
              <td className="px-2 py-1">{b.notes ?? ""}</td>
              <td className="space-x-1 px-2 py-1 text-right">
                {esAdmin && (
                  <>
                    <Button variant="ghost" aria-label={`Editar bloqueo ${BLOCK_REASON_LABEL[b.reason]}`} onClick={() => setForm(b)}>
                      Editar
                    </Button>
                    <Button
                      variant="secondary"
                      aria-label={`Retirar bloqueo ${BLOCK_REASON_LABEL[b.reason]}`}
                      onClick={() => void retirar(b)}
                    >
                      Retirar
                    </Button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {form !== null && (
        <BlockForm
          tz={tz}
          modo={form}
          propio={user?.role === "odontologo" ? user.professional_id : null}
          puedeCancelar={deMostrador}
          professionals={(professionals.data ?? []).filter((p) => p.active)}
          chairs={(chairs.data ?? []).filter((c) => c.active)}
          nombreProf={nombreProf}
          onClose={() => setForm(null)}
          onDone={(m) => void refrescar(m)}
        />
      )}
    </section>
  );
}

function splitLocal(iso: string, tz: string): { fecha: string; hora: string } {
  const d = new Date(iso);
  return { fecha: dateKeyOf(d, tz), hora: formatTime(d, tz) };
}

function BlockForm({
  tz,
  modo,
  propio,
  puedeCancelar,
  professionals,
  chairs,
  nombreProf,
  onClose,
  onDone
}: {
  tz: string;
  modo: "nuevo" | "cierre" | Block;
  propio: string | null;
  puedeCancelar: boolean;
  professionals: { id: string; display_name: string }[];
  chairs: { id: string; name: string }[];
  nombreProf: Map<string, string>;
  onClose: () => void;
  onDone: (mensaje: string) => void;
}): JSX.Element {
  const edicion = typeof modo === "object" ? modo : null;
  const cierre = modo === "cierre";
  const inicio = edicion !== null ? splitLocal(edicion.starts_at, tz) : { fecha: "", hora: "" };
  const fin = edicion !== null ? splitLocal(edicion.ends_at, tz) : { fecha: "", hora: "" };
  const [professionalId, setProfessionalId] = useState(edicion?.professional_id ?? propio ?? "");
  const [chairId, setChairId] = useState(edicion?.chair_id ?? "");
  const [desdeFecha, setDesdeFecha] = useState(inicio.fecha);
  const [desdeHora, setDesdeHora] = useState(inicio.hora);
  const [hastaFecha, setHastaFecha] = useState(fin.fecha);
  const [hastaHora, setHastaHora] = useState(fin.hora);
  const [reason, setReason] = useState<BlockReason>(edicion?.reason ?? (cierre ? "feriado" : "vacaciones"));
  const [notes, setNotes] = useState(edicion?.notes ?? "");
  const [error, setError] = useState<string | null>(null);
  const [afectados, setAfectados] = useState<{ envio: Envio; turnos: Appointment[] } | null>(null);
  const [motivoCancelacion, setMotivoCancelacion] = useState<CancellationReason>("bloqueo");
  const [notaCancelacion, setNotaCancelacion] = useState("");

  async function cargarAfectados(ids: string[], envio: Envio): Promise<void> {
    const turnos = await Promise.all(ids.map((id) => apiFetch<Appointment>(`/api/appointments/${id}`)));
    setAfectados({ envio, turnos });
  }

  async function mandar(envio: Envio, cancelar?: CancelInstruction[]): Promise<void> {
    setError(null);
    try {
      if (envio.kind === "create" && cierre) {
        await apiFetch("/api/blocks/closure", { method: "POST", body: { ...envio.body, cancel_appointments: cancelar } });
        onDone("Cierre creado");
      } else if (envio.kind === "create") {
        await apiFetch("/api/blocks", { method: "POST", body: cancelar === undefined ? envio.body : { ...envio.body, cancel_appointments: cancelar } });
        onDone("Bloqueo creado");
      } else {
        await apiFetch(`/api/blocks/${envio.id}`, { method: "PATCH", body: cancelar === undefined ? envio.body : { ...envio.body, cancel_appointments: cancelar } });
        onDone("Bloqueo actualizado");
      }
    } catch (e) {
      const ids = e instanceof ApiError ? e.extra.appointments : undefined;
      if (e instanceof ApiError && e.detail === "block_conflicts" && Array.isArray(ids)) {
        await cargarAfectados(ids.filter((i): i is string => typeof i === "string"), envio).catch(() => undefined);
      }
      setError(messageFor(e));
    }
  }

  function enviar(e: FormEvent): void {
    e.preventDefault();
    setAfectados(null);
    const startsAt = fromZonedWallTime(desdeFecha, cierre ? "00:00" : desdeHora, tz);
    const endsAt = fromZonedWallTime(hastaFecha, cierre ? "00:00" : hastaHora, tz);
    if (startsAt === null || endsAt === null || endsAt <= startsAt) {
      setError("Revisá el rango: el fin debe ser posterior al inicio");
      return;
    }
    if (!cierre && edicion === null && professionalId === "" && chairId === "") {
      setError("Elegí un profesional, un sillón o ambos");
      return;
    }
    const base: BlockBody = { starts_at: startsAt.toISOString(), ends_at: endsAt.toISOString(), reason };
    if (notes.trim() !== "") {
      base.notes = notes.trim();
    }
    if (edicion !== null) {
      const body: Partial<BlockBody> = {};
      if (base.starts_at !== new Date(edicion.starts_at).toISOString()) body.starts_at = base.starts_at;
      if (base.ends_at !== new Date(edicion.ends_at).toISOString()) body.ends_at = base.ends_at;
      if (base.reason !== edicion.reason) body.reason = base.reason;
      if ((base.notes ?? null) !== edicion.notes) body.notes = base.notes;
      void mandar({ kind: "edit", id: edicion.id, body });
      return;
    }
    if (!cierre) {
      if (professionalId !== "") base.professional_id = professionalId;
      if (chairId !== "") base.chair_id = chairId;
    }
    void mandar({ kind: "create", body: base });
  }

  function resolver(): void {
    if (afectados === null) {
      return;
    }
    const nota = notaCancelacion.trim();
    void mandar(
      afectados.envio,
      afectados.turnos.map((t) => ({
        appointment_id: t.id,
        reason: motivoCancelacion,
        ...(nota !== "" ? { note: nota } : {})
      }))
    );
  }

  const titulo = cierre ? "Cierre de clínica" : edicion !== null ? "Editar bloqueo" : "Nuevo bloqueo";
  const n = afectados?.turnos.length ?? 0;
  return (
    <Modal title={titulo} onClose={onClose}>
      <form onSubmit={enviar} className="space-y-3" noValidate>
        {!cierre && (
          <div className="grid grid-cols-2 gap-2">
            <SelectField
              label="Profesional"
              value={professionalId}
              disabled={propio !== null || edicion !== null}
              onChange={(e) => setProfessionalId(e.target.value)}
            >
              {propio === null && <option value="">Ninguno</option>}
              {professionals.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
            </SelectField>
            <SelectField label="Sillón" value={chairId} disabled={edicion !== null} onChange={(e) => setChairId(e.target.value)}>
              <option value="">Ninguno</option>
              {chairs.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </SelectField>
          </div>
        )}
        <div className="grid grid-cols-2 gap-2">
          <TextField label="Desde (fecha)" type="date" value={desdeFecha} onChange={(e) => setDesdeFecha(e.target.value)} />
          {!cierre && <TextField label="Desde (hora)" type="time" value={desdeHora} onChange={(e) => setDesdeHora(e.target.value)} />}
          <TextField label="Hasta (fecha)" type="date" value={hastaFecha} onChange={(e) => setHastaFecha(e.target.value)} />
          {!cierre && <TextField label="Hasta (hora)" type="time" value={hastaHora} onChange={(e) => setHastaHora(e.target.value)} />}
        </div>
        {cierre && <p className="text-xs opacity-70">El cierre va de las 00:00 del primer día a las 00:00 del último (excluido), en todos los sillones activos.</p>}
        <SelectField label="Motivo" value={reason} onChange={(e) => setReason(e.target.value as BlockReason)}>
          {MOTIVOS.map((m) => (
            <option key={m} value={m}>
              {BLOCK_REASON_LABEL[m]}
            </option>
          ))}
        </SelectField>
        <TextArea label="Notas" value={notes} maxLength={500} onChange={(e) => setNotes(e.target.value)} />

        {afectados !== null && (
          <section aria-label="Turnos afectados" className="space-y-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm">
            <p className="font-medium">El bloqueo pisa estos turnos:</p>
            <ul className="list-inside list-disc">
              {afectados.turnos.map((t) => (
                <li key={t.id}>
                  {`${formatDayLabel(dateKeyOf(new Date(t.starts_at), tz))} ${formatTime(new Date(t.starts_at), tz)} · ${nombreProf.get(t.professional_id) ?? "Profesional"}`}
                </li>
              ))}
            </ul>
            {puedeCancelar ? (
              <div className="space-y-2">
                <SelectField
                  label="Motivo de cancelación"
                  value={motivoCancelacion}
                  onChange={(e) => setMotivoCancelacion(e.target.value as CancellationReason)}
                >
                  {MOTIVOS_CANCELACION.map((m) => (
                    <option key={m} value={m}>
                      {CANCELLATION_REASON_LABEL[m]}
                    </option>
                  ))}
                </SelectField>
                <TextArea label="Nota de cancelación" value={notaCancelacion} maxLength={500} onChange={(e) => setNotaCancelacion(e.target.value)} />
                <Button variant="danger" onClick={resolver}>
                  {`Cancelar ${n} turno${n === 1 ? "" : "s"} y ${edicion !== null ? "guardar" : "crear"} el bloqueo`}
                </Button>
              </div>
            ) : (
              <p>Para bloquear este rango, recepción debe resolver los turnos primero.</p>
            )}
          </section>
        )}

        {error !== null && afectados === null && <Alert>{error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit">{cierre ? "Guardar cierre" : "Guardar bloqueo"}</Button>
        </div>
      </form>
    </Modal>
  );
}

export default BlocksPage;
