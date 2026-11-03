/**
 * Grilla de agenda propia (D5): columnas (sillones o días) × minutos. Turnos y
 * bloqueos se posicionan en píxeles por minuto; lo que se solapa va en carriles.
 */
import { memo, type CSSProperties, type MouseEvent } from "react";
import type { Appointment } from "../../shared/api/types";
import { formatTime } from "../../shared/time/zoned";
import { SLOT_MIN, type PlacedItem, type VisibleRange } from "./layout";
import { STATUS_LABEL, STATUS_STYLE } from "./labels";

export const PX_PER_MIN = 1.2;

export interface Column {
  key: string;
  label: string;
}

export interface GridAppointment {
  appointment: Appointment;
  placed: PlacedItem;
  color: string;
  pendingSoon: boolean;
}

export interface GridBlock {
  key: string;
  placed: PlacedItem;
  label: string;
}

function posicion(placed: PlacedItem): CSSProperties {
  const ancho = 100 / placed.lanes;
  return {
    top: placed.top * PX_PER_MIN,
    height: Math.max(placed.height * PX_PER_MIN, 18),
    left: `calc(${placed.lane * ancho}% + 2px)`,
    width: `calc(${ancho}% - 4px)`
  };
}

const AppointmentCard = memo(function AppointmentCard({
  item,
  tz,
  onSelect
}: {
  item: GridAppointment;
  tz: string;
  onSelect: (appointment: Appointment) => void;
}): JSX.Element {
  const { appointment, color, pendingSoon } = item;
  const hora = formatTime(new Date(appointment.starts_at), tz);
  const estado = STATUS_LABEL[appointment.status];
  return (
    <button
      type="button"
      aria-label={`${hora} ${appointment.patient.full_name} · ${estado}`}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(appointment);
      }}
      className={`absolute overflow-hidden rounded border-l-4 bg-white px-1.5 py-0.5 text-left text-xs shadow-sm hover:z-10 hover:shadow focus:z-10 focus:outline-none focus-visible:ring-2 focus-visible:ring-dental-600 ${
        pendingSoon ? "ring-2 ring-amber-400" : ""
      } ${appointment.status === "cancelled" ? "opacity-60" : ""}`}
      style={{ ...posicion(item.placed), borderLeftColor: color }}
    >
      <span className="font-semibold">{hora}</span> <span>{appointment.patient.full_name}</span>
      <span className="mt-0.5 flex flex-wrap gap-1">
        <span className={`rounded px-1 ${STATUS_STYLE[appointment.status]}`}>{estado}</span>
        {appointment.is_overbooking && (
          <span className="rounded bg-violet-100 px-1 text-violet-900">Sobreturno</span>
        )}
        {pendingSoon && <span className="rounded bg-amber-200 px-1 text-amber-950">Sin confirmar</span>}
      </span>
    </button>
  );
});

function AgendaGrid({
  columns,
  range,
  appointments,
  blocks,
  tz,
  onSelect,
  onEmptySlot
}: {
  columns: readonly Column[];
  range: VisibleRange;
  appointments: readonly GridAppointment[];
  blocks: readonly GridBlock[];
  tz: string;
  onSelect: (appointment: Appointment) => void;
  onEmptySlot?: (column: string, minuteOfDay: number) => void;
}): JSX.Element {
  const alto = (range.endMin - range.startMin) * PX_PER_MIN;
  const horas: number[] = [];
  for (let m = range.startMin; m < range.endMin; m += 60) {
    horas.push(m);
  }

  function clickVacio(column: string, event: MouseEvent<HTMLDivElement>): void {
    if (onEmptySlot === undefined) {
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const minutos = (event.clientY - rect.top) / PX_PER_MIN;
    const redondeado = Math.floor(minutos / SLOT_MIN) * SLOT_MIN;
    onEmptySlot(column, range.startMin + redondeado);
  }

  return (
    <div role="grid" aria-label="Agenda" className="overflow-x-auto rounded border border-dental-600/20 bg-white">
      <div role="row" className="flex border-b border-dental-600/20 bg-dental-50">
        <div className="w-14 shrink-0" />
        {columns.map((c) => (
          <div key={c.key} role="columnheader" className="min-w-[9rem] flex-1 px-2 py-1 text-sm font-medium">
            {c.label}
          </div>
        ))}
      </div>
      <div role="row" className="flex">
        <div className="relative w-14 shrink-0 text-right text-xs opacity-70" style={{ height: alto }}>
          {horas.map((m) => (
            <div key={m} className="absolute right-1" style={{ top: (m - range.startMin) * PX_PER_MIN }}>
              {String(Math.floor(m / 60)).padStart(2, "0")}:00
            </div>
          ))}
        </div>
        {columns.map((c) => (
          <div
            key={c.key}
            role="gridcell"
            aria-label={c.label}
            className="relative min-w-[9rem] flex-1 border-l border-dental-600/10"
            style={{
              height: alto,
              backgroundImage: `repeating-linear-gradient(to bottom, transparent 0, transparent ${60 * PX_PER_MIN - 1}px, rgb(14 124 123 / 0.12) ${60 * PX_PER_MIN - 1}px, rgb(14 124 123 / 0.12) ${60 * PX_PER_MIN}px)`
            }}
            onClick={(e) => clickVacio(c.key, e)}
          >
            {blocks
              .filter((b) => b.placed.column === c.key)
              .map((b) => (
                <div
                  key={b.key}
                  role="note"
                  aria-label={b.label}
                  className="absolute inset-x-0 overflow-hidden px-1 text-[11px] text-stone-700"
                  style={{
                    top: b.placed.top * PX_PER_MIN,
                    height: b.placed.height * PX_PER_MIN,
                    backgroundImage:
                      "repeating-linear-gradient(45deg, rgb(120 113 108 / 0.18) 0 6px, transparent 6px 12px)"
                  }}
                >
                  {b.label}
                </div>
              ))}
            {appointments
              .filter((a) => a.placed.column === c.key)
              .map((a) => (
                <AppointmentCard key={a.appointment.id} item={a} tz={tz} onSelect={onSelect} />
              ))}
          </div>
        ))}
      </div>
    </div>
  );
}

export default memo(AgendaGrid);
