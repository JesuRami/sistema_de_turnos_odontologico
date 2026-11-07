/**
 * Agenda del personal (US-010, Flujo 4): vista día por sillón y semana por día,
 * en la zona horaria de la clínica, con filtros y distintivos. La API es la
 * autoridad: esta pantalla solo muestra y ofrece lo que el rol puede pedir.
 * Admin y recepción ven además el panel de seguimiento de recordatorios (C-11).
 */
import { useMemo, useState } from "react";
import type { Appointment, AppointmentStatus, Block } from "../../shared/api/types";
import {
  useAppointments,
  useBlocks,
  useChairs,
  useClinic,
  useFollowUp,
  useProfessionals,
  useSchedules
} from "../../shared/api/queries";
import { useAuth } from "../../shared/auth/AuthProvider";
import { useClock } from "../../shared/time/now";
import {
  addDays,
  dateKeyOf,
  formatDayLabel,
  formatTime,
  startOfWeekKey,
  zonedDayRange,
  zonedRange,
  type DateKey
} from "../../shared/time/zoned";
import { Alert, Button, PageTitle, SelectField } from "../../shared/ui";
import AgendaGrid, { type Column, type GridAppointment, type GridBlock } from "./AgendaGrid";
import AppointmentDetail from "./AppointmentDetail";
import AppointmentForm, { type FormSeed } from "./AppointmentForm";
import { colorFor, isPendingSoon, layoutItems, visibleRange, type GridItem } from "./layout";
import { BLOCK_REASON_LABEL, STATUS_LABEL } from "./labels";

type View = "day" | "week";

const ESTADOS: AppointmentStatus[] = ["pending", "confirmed", "present", "absent", "no_show", "cancelled"];

/** Recorta un bloqueo a cada día del rango (un bloqueo de vacaciones cruza días). */
function blockPieces(block: Block, days: readonly DateKey[], tz: string): { day: DateKey; start: Date; end: Date }[] {
  const inicio = new Date(block.starts_at);
  const fin = new Date(block.ends_at);
  return days.flatMap((day) => {
    const { from, to } = zonedDayRange(day, tz);
    const start = inicio > from ? inicio : from;
    const end = fin < to ? fin : to;
    return end > start ? [{ day, start, end }] : [];
  });
}

function AgendaPage(): JSX.Element {
  const { user } = useAuth();
  const clock = useClock();
  const clinic = useClinic();
  const professionals = useProfessionals();
  const chairs = useChairs();
  const schedules = useSchedules();
  const tz = clinic.data?.timezone ?? null;

  const [view, setView] = useState<View>("day");
  const [anchor, setAnchor] = useState<DateKey | null>(null);
  const [profFilter, setProfFilter] = useState("");
  const [chairFilter, setChairFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selected, setSelected] = useState<Appointment | null>(null);
  const [formSeed, setFormSeed] = useState<FormSeed | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [soloLlamar, setSoloLlamar] = useState(false);

  const hoy = tz !== null ? dateKeyOf(clock(), tz) : null;
  const dia = anchor ?? hoy;
  const days = useMemo<DateKey[]>(() => {
    if (dia === null) {
      return [];
    }
    if (view === "day") {
      return [dia];
    }
    const lunes = startOfWeekKey(dia);
    return Array.from({ length: 7 }, (_, i) => addDays(lunes, i));
  }, [dia, view]);
  const range = useMemo(
    () => (tz !== null && days[0] !== undefined ? zonedRange(days[0], days.length, tz) : null),
    [tz, days]
  );

  const appointments = useAppointments(range);
  const blocks = useBlocks(range);
  const role = user?.role ?? "odontologo";
  const deMostrador = role === "admin" || role === "recepcion";
  const seguimiento = useFollowUp(range, deMostrador);
  // Sin turnos para llamar el filtro no vacía la grilla (spec web/agenda-board).
  const paraLlamar = useMemo(() => {
    const ids = (seguimiento.data?.items ?? []).map((i) => i.appointment_id);
    return soloLlamar && ids.length > 0 ? new Set(ids) : null;
  }, [seguimiento.data, soloLlamar]);

  const profesionales = useMemo(() => professionals.data ?? [], [professionals.data]);
  const sillonesActivos = useMemo(() => (chairs.data ?? []).filter((c) => c.active), [chairs.data]);
  const porProfesional = useMemo(() => new Map(profesionales.map((p) => [p.id, p])), [profesionales]);

  const columns = useMemo<Column[]>(() => {
    if (view === "week") {
      return days.map((d) => ({ key: d, label: formatDayLabel(d) }));
    }
    return sillonesActivos
      .filter((c) => chairFilter === "" || c.id === chairFilter)
      .map((c) => ({ key: c.id, label: c.name }));
  }, [view, days, sillonesActivos, chairFilter]);

  const visible = useMemo(() => visibleRange(schedules.data ?? [], days), [schedules.data, days]);

  const gridAppointments = useMemo<GridAppointment[]>(() => {
    if (tz === null) {
      return [];
    }
    const ahora = clock();
    const filtrados = (appointments.data ?? []).filter(
      (a) =>
        (profFilter === "" || a.professional_id === profFilter) &&
        (chairFilter === "" || a.chair_id === chairFilter) &&
        (statusFilter === "" ? a.status !== "cancelled" : a.status === statusFilter) &&
        (paraLlamar === null || paraLlamar.has(a.id))
    );
    const items: GridItem[] = filtrados.map((a) => ({
      id: a.id,
      start: new Date(a.starts_at),
      end: new Date(a.ends_at),
      column: view === "week" ? dateKeyOf(new Date(a.starts_at), tz) : a.chair_id
    }));
    const placed = new Map(layoutItems(items, visible, tz).map((p) => [p.id, p]));
    return filtrados.flatMap((a) => {
      const p = placed.get(a.id);
      const prof = porProfesional.get(a.professional_id);
      return p === undefined
        ? []
        : [
            {
              appointment: a,
              placed: p,
              color: colorFor(prof ?? { id: a.professional_id, color: null }),
              pendingSoon: isPendingSoon(a.status, new Date(a.starts_at), ahora)
            }
          ];
    });
  }, [appointments.data, profFilter, chairFilter, statusFilter, paraLlamar, view, visible, tz, porProfesional, clock]);

  const gridBlocks = useMemo<GridBlock[]>(() => {
    if (tz === null) {
      return [];
    }
    const piezas: { item: GridItem; label: string }[] = [];
    for (const b of blocks.data ?? []) {
      if (b.professional_id !== null && profFilter !== "" && b.professional_id !== profFilter) {
        continue;
      }
      if (b.chair_id !== null && chairFilter !== "" && b.chair_id !== chairFilter) {
        continue;
      }
      const quien = b.professional_id !== null ? porProfesional.get(b.professional_id)?.display_name : undefined;
      for (const pieza of blockPieces(b, days, tz)) {
        const label = `Bloqueo · ${BLOCK_REASON_LABEL[b.reason]} ${formatTime(pieza.start, tz)}–${formatTime(pieza.end, tz)}${quien !== undefined ? ` · ${quien}` : ""}`;
        const columnas =
          view === "week"
            ? [pieza.day]
            : b.chair_id !== null
              ? [b.chair_id]
              : columns.map((c) => c.key);
        for (const column of columnas) {
          piezas.push({ item: { id: `${b.id}:${pieza.day}:${column}`, start: pieza.start, end: pieza.end, column }, label });
        }
      }
    }
    const placed = new Map(layoutItems(piezas.map((p) => p.item), visible, tz).map((p) => [p.id, p]));
    return piezas.flatMap((p) => {
      const ubicado = placed.get(p.item.id);
      return ubicado === undefined ? [] : [{ key: p.item.id, placed: { ...ubicado, lane: 0, lanes: 1 }, label: p.label }];
    });
  }, [blocks.data, profFilter, chairFilter, days, tz, view, columns, visible, porProfesional]);

  if (clinic.isError) {
    return <Alert>No se pudo cargar la clínica. Recargá la página.</Alert>;
  }
  if (tz === null || dia === null) {
    return <p className="text-sm">Cargando agenda…</p>;
  }

  const paso = view === "day" ? 1 : 7;
  const titulo = view === "day" ? formatDayLabel(dia) : `Semana del ${formatDayLabel(days[0] ?? dia)}`;
  const contexto = {
    tz,
    role,
    professionals: profesionales,
    chairs: sillonesActivos,
    schedules: schedules.data ?? []
  };

  return (
    <section aria-label="Agenda">
      <PageTitle
        actions={
          deMostrador && (
            <Button onClick={() => setFormSeed({ day: dia })}>Nuevo turno</Button>
          )
        }
      >
        {titulo}
        {dia === hoy && view === "day" ? " · hoy" : ""}
      </PageTitle>

      <div className="mb-3 flex flex-wrap items-end gap-2">
        <Button variant="secondary" onClick={() => setAnchor(addDays(dia, -paso))}>
          Anterior
        </Button>
        <Button variant="secondary" onClick={() => setAnchor(null)}>
          Hoy
        </Button>
        <Button variant="secondary" onClick={() => setAnchor(addDays(dia, paso))}>
          Siguiente
        </Button>
        <div className="ml-2 flex gap-1" role="group" aria-label="Vista">
          <Button variant={view === "day" ? "primary" : "secondary"} aria-pressed={view === "day"} onClick={() => setView("day")}>
            Día
          </Button>
          <Button variant={view === "week" ? "primary" : "secondary"} aria-pressed={view === "week"} onClick={() => setView("week")}>
            Semana
          </Button>
        </div>
        <div className="ml-auto flex flex-wrap gap-2">
          {profesionales.length > 1 && (
            <SelectField label="Profesional" value={profFilter} onChange={(e) => setProfFilter(e.target.value)}>
              <option value="">Todos</option>
              {profesionales.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name}
                </option>
              ))}
            </SelectField>
          )}
          <SelectField label="Sillón" value={chairFilter} onChange={(e) => setChairFilter(e.target.value)}>
            <option value="">Todos</option>
            {sillonesActivos.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </SelectField>
          <SelectField label="Estado" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">Todos menos cancelados</option>
            {ESTADOS.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </SelectField>
        </div>
      </div>

      {deMostrador && (
        <section
          aria-label="Seguimiento de recordatorios"
          className="mb-3 flex flex-wrap items-center gap-3 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-950"
        >
          {seguimiento.isError ? (
            <span>No se pudo cargar el seguimiento de recordatorios.</span>
          ) : (
            <>
              <span>{`${seguimiento.data?.totals.no_response ?? 0} sin confirmar`}</span>
              <span>{`${seguimiento.data?.totals.delivery_failed ?? 0} con fallo de envío`}</span>
            </>
          )}
          <Button
            variant={soloLlamar ? "primary" : "secondary"}
            className="ml-auto"
            aria-pressed={soloLlamar}
            onClick={() => setSoloLlamar((v) => !v)}
          >
            Solo para llamar
          </Button>
        </section>
      )}

      {aviso !== null && (
        <div className="mb-3">
          <Alert tone="success">{aviso}</Alert>
        </div>
      )}
      {(appointments.isError || blocks.isError) && (
        <div className="mb-3">
          <Alert>No se pudieron cargar los turnos del rango. Reintentá en unos segundos.</Alert>
        </div>
      )}

      <AgendaGrid
        columns={columns}
        range={visible}
        appointments={gridAppointments}
        blocks={gridBlocks}
        tz={tz}
        onSelect={setSelected}
        onEmptySlot={
          deMostrador
            ? (column, minuto) =>
                setFormSeed({
                  day: view === "week" ? column : dia,
                  chairId: view === "day" ? column : undefined,
                  time: `${String(Math.floor(minuto / 60)).padStart(2, "0")}:${String(minuto % 60).padStart(2, "0")}`
                })
            : undefined
        }
      />

      {selected !== null && (
        <AppointmentDetail
          appointment={selected}
          context={contexto}
          onClose={() => setSelected(null)}
          onReschedule={(a) => {
            setSelected(null);
            setFormSeed({ day: dateKeyOf(new Date(a.starts_at), tz), appointment: a });
          }}
          onDone={(mensaje) => {
            setSelected(null);
            setAviso(mensaje);
          }}
        />
      )}
      {formSeed !== null && (
        <AppointmentForm
          seed={formSeed}
          context={contexto}
          onClose={() => setFormSeed(null)}
          onDone={(mensaje) => {
            setFormSeed(null);
            setAviso(mensaje);
          }}
        />
      )}
    </section>
  );
}

export default AgendaPage;
