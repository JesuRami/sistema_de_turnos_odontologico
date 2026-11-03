/**
 * Plantilla semanal (US-002): franjas por profesional y sillón. El anti-solape
 * lo garantiza la base (C-04); ante `409 schedule_overlap` se marcan las franjas
 * en conflicto que devuelve la API.
 */
import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { ApiError, apiFetch } from "../../shared/api/client";
import { messageFor } from "../../shared/api/errors";
import { queryKeys, useChairs, useClinic, useProfessionals, useSchedules } from "../../shared/api/queries";
import type { ScheduleRule } from "../../shared/api/types";
import { useClock } from "../../shared/time/now";
import { dateKeyOf } from "../../shared/time/zoned";
import { Alert, Button, Modal, PageTitle, SelectField, TextField } from "../../shared/ui";

export const DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"];

const hhmm = (t: string): string => t.slice(0, 5);

function SchedulesAdmin(): JSX.Element {
  const queryClient = useQueryClient();
  const clock = useClock();
  const clinic = useClinic();
  const schedules = useSchedules();
  const professionals = useProfessionals();
  const chairs = useChairs();
  const [abierto, setAbierto] = useState(false);
  const [conflictos, setConflictos] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const nombreProf = new Map((professionals.data ?? []).map((p) => [p.id, p.display_name]));
  const nombreSillon = new Map((chairs.data ?? []).map((c) => [c.id, c.name]));
  const reglas = [...(schedules.data ?? [])].sort(
    (a, b) =>
      (nombreProf.get(a.professional_id) ?? "").localeCompare(nombreProf.get(b.professional_id) ?? "") ||
      a.weekday - b.weekday ||
      a.start_time.localeCompare(b.start_time)
  );
  const hoy = clinic.data !== undefined ? dateKeyOf(clock(), clinic.data.timezone) : "";

  async function mutar(accion: () => Promise<unknown>): Promise<boolean> {
    setError(null);
    setConflictos([]);
    try {
      await accion();
      await queryClient.invalidateQueries({ queryKey: queryKeys.schedules });
      return true;
    } catch (e) {
      if (e instanceof ApiError && Array.isArray(e.extra.conflicts)) {
        setConflictos(e.extra.conflicts.filter((c): c is string => typeof c === "string"));
      }
      setError(messageFor(e));
      return false;
    }
  }

  const etiqueta = (r: ScheduleRule): string =>
    `${DIAS[r.weekday] ?? ""} ${hhmm(r.start_time)}–${hhmm(r.end_time)}`;

  return (
    <section>
      <PageTitle actions={<Button onClick={() => setAbierto(true)}>Nueva franja</Button>}>Plantilla semanal</PageTitle>
      {error !== null && !abierto && <Alert>{error}</Alert>}
      <table className="mt-2 w-full rounded bg-white text-sm shadow-sm">
        <thead className="bg-dental-50 text-left">
          <tr>
            <th className="px-2 py-1">Día</th>
            <th className="px-2 py-1">Franja</th>
            <th className="px-2 py-1">Profesional</th>
            <th className="px-2 py-1">Sillón</th>
            <th className="px-2 py-1">Turno</th>
            <th className="px-2 py-1">Vigencia</th>
            <th className="px-2 py-1">Estado</th>
            <th className="px-2 py-1">
              <span className="sr-only">Acciones</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {reglas.map((r) => (
            <tr key={r.id} className={`border-t border-dental-600/10 ${conflictos.includes(r.id) ? "bg-amber-50" : ""}`}>
              <td className="px-2 py-1">{DIAS[r.weekday]}</td>
              <td className="px-2 py-1">
                {hhmm(r.start_time)}–{hhmm(r.end_time)}
                {conflictos.includes(r.id) && (
                  <span className="ml-2 rounded bg-amber-200 px-1 text-xs">En conflicto</span>
                )}
              </td>
              <td className="px-2 py-1">{nombreProf.get(r.professional_id) ?? "—"}</td>
              <td className="px-2 py-1">{nombreSillon.get(r.chair_id) ?? "—"}</td>
              <td className="px-2 py-1">{r.slot_duration_min} min</td>
              <td className="px-2 py-1">
                desde {r.valid_from}
                {r.valid_to !== null ? ` hasta ${r.valid_to}` : ""}
              </td>
              <td className="px-2 py-1">{r.active ? "Activa" : "Inactiva"}</td>
              <td className="px-2 py-1 text-right">
                <Button
                  variant="secondary"
                  aria-label={`${r.active ? "Desactivar" : "Reactivar"} franja ${etiqueta(r)}`}
                  onClick={() =>
                    void mutar(() => apiFetch(`/api/schedules/${r.id}`, { method: "PATCH", body: { active: !r.active } }))
                  }
                >
                  {r.active ? "Desactivar" : "Reactivar"}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {abierto && (
        <RuleForm
          hoy={hoy}
          professionals={(professionals.data ?? []).filter((p) => p.active)}
          chairs={(chairs.data ?? []).filter((c) => c.active)}
          error={error}
          onClose={() => {
            setAbierto(false);
            setError(null);
          }}
          onSubmit={async (body) => {
            if (await mutar(() => apiFetch("/api/schedules", { method: "POST", body }))) {
              setAbierto(false);
            }
          }}
        />
      )}
    </section>
  );
}

interface RuleBody {
  professional_id: string;
  chair_id: string;
  weekday: number;
  start_time: string;
  end_time: string;
  slot_duration_min: number;
  valid_from: string;
  valid_to?: string;
}

function RuleForm({
  hoy,
  professionals,
  chairs,
  error,
  onClose,
  onSubmit
}: {
  hoy: string;
  professionals: { id: string; display_name: string }[];
  chairs: { id: string; name: string }[];
  error: string | null;
  onClose: () => void;
  onSubmit: (body: RuleBody) => Promise<void>;
}): JSX.Element {
  const [professionalId, setProfessionalId] = useState(professionals[0]?.id ?? "");
  const [chairId, setChairId] = useState(chairs[0]?.id ?? "");
  const [weekday, setWeekday] = useState(0);
  const [desde, setDesde] = useState("");
  const [hasta, setHasta] = useState("");
  const [slot, setSlot] = useState(30);
  const [validFrom, setValidFrom] = useState(hoy);
  const [validTo, setValidTo] = useState("");
  const [local, setLocal] = useState<string | null>(null);

  function enviar(e: FormEvent): void {
    e.preventDefault();
    if (desde === "" || hasta === "" || desde >= hasta) {
      setLocal("La franja necesita un inicio anterior al fin");
      return;
    }
    setLocal(null);
    const body: RuleBody = {
      professional_id: professionalId,
      chair_id: chairId,
      weekday,
      start_time: desde,
      end_time: hasta,
      slot_duration_min: slot,
      valid_from: validFrom
    };
    if (validTo !== "") {
      body.valid_to = validTo;
    }
    void onSubmit(body);
  }

  return (
    <Modal title="Nueva franja" onClose={onClose}>
      <form onSubmit={enviar} className="space-y-3" noValidate>
        <div className="grid grid-cols-2 gap-2">
          <SelectField label="Profesional" value={professionalId} onChange={(e) => setProfessionalId(e.target.value)}>
            {professionals.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
              </option>
            ))}
          </SelectField>
          <SelectField label="Sillón" value={chairId} onChange={(e) => setChairId(e.target.value)}>
            {chairs.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </SelectField>
          <SelectField label="Día" value={String(weekday)} onChange={(e) => setWeekday(Number(e.target.value))}>
            {DIAS.map((d, i) => (
              <option key={d} value={i}>
                {d}
              </option>
            ))}
          </SelectField>
          <TextField
            label="Duración del turno (min)"
            type="number"
            min={5}
            max={480}
            value={slot}
            onChange={(e) => setSlot(Number(e.target.value))}
          />
          <TextField label="Desde" type="time" value={desde} onChange={(e) => setDesde(e.target.value)} />
          <TextField label="Hasta" type="time" value={hasta} onChange={(e) => setHasta(e.target.value)} />
          <TextField label="Vigente desde" type="date" value={validFrom} onChange={(e) => setValidFrom(e.target.value)} />
          <TextField label="Vigente hasta" type="date" value={validTo} onChange={(e) => setValidTo(e.target.value)} />
        </div>
        {(local ?? error) !== null && <Alert>{local ?? error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit">Guardar</Button>
        </div>
      </form>
    </Modal>
  );
}

export default SchedulesAdmin;
