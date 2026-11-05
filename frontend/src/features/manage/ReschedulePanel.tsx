/**
 * Reprogramación (D8): solo los huecos que devuelve el servidor para el mismo profesional,
 * agrupados por día en la zona de la clínica, con el horario actual marcado. Sin huecos, se
 * deriva a la clínica en lugar de mostrar una grilla vacía.
 */
import { useMemo, useState } from "react";
import { useClock } from "../../shared/time/now";
import {
  dateKeyOf,
  formatDayLabel,
  formatTime,
  zonedRange,
  type DateKey
} from "../../shared/time/zoned";
import { CHOICE, CHOICE_OFF, CHOICE_ON } from "../booking/ProfessionalStep";
import ManageContact, { PRIMARY, SECONDARY } from "./ManageContact";
import { RESCHEDULE_DAYS, useManageAvailability } from "./queries";
import type { ManageSlot, ManageView } from "./types";

interface ReschedulePanelProps {
  token: string;
  view: ManageView;
  pending: boolean;
  onSubmit: (startsAt: string) => void;
  onClose: () => void;
}

function sameInstant(a: string, b: string): boolean {
  return new Date(a).getTime() === new Date(b).getTime();
}

function ReschedulePanel({ token, view, pending, onSubmit, onClose }: ReschedulePanelProps): JSX.Element {
  const clock = useClock();
  const tz = view.clinic.timezone;
  const actual = view.appointment.starts_at;
  const range = useMemo(
    () => zonedRange(dateKeyOf(clock(), tz), RESCHEDULE_DAYS, tz),
    [clock, tz]
  );
  const huecos = useManageAvailability(token, range, true);
  const [dia, setDia] = useState<DateKey | null>(null);
  const [elegido, setElegido] = useState<string | null>(null);

  const porDia = useMemo(() => {
    const dias = new Map<DateKey, ManageSlot[]>();
    for (const slot of huecos.data?.slots ?? []) {
      const clave = dateKeyOf(new Date(slot.starts_at), tz);
      dias.set(clave, [...(dias.get(clave) ?? []), slot]);
    }
    return dias;
  }, [huecos.data, tz]);
  const dias = [...porDia.keys()].sort();
  // Solo el horario actual no es un cambio: sin otros huecos, se deriva a la clínica.
  const libres = (huecos.data?.slots ?? []).filter((s) => !sameInstant(s.starts_at, actual));

  return (
    <section className="mt-4 rounded-lg border border-dental-600/20 bg-white p-4" aria-labelledby="nuevo-horario">
      <h2 id="nuevo-horario" className="text-lg font-semibold">
        Elegí un nuevo horario
      </h2>
      <p className="mt-1 text-xs opacity-70">
        Solo se muestran horarios libres con {view.appointment.professional_display_name}.
      </p>
      <div aria-live="polite">
        {huecos.isPending && <p className="mt-3 text-sm">Buscando horarios libres…</p>}
      </div>
      {huecos.isError && (
        <p role="alert" className="mt-3 text-sm">
          No pudimos cargar los horarios. Probá de nuevo en unos minutos.
        </p>
      )}
      {huecos.isSuccess && libres.length === 0 && (
        <div className="mt-3 text-sm">
          <p>No hay horarios libres en los próximos {RESCHEDULE_DAYS} días. Hablá con la clínica.</p>
          <ManageContact clinicName={view.clinic.name} phone={view.clinic.phone} />
        </div>
      )}
      {huecos.isSuccess && libres.length > 0 && (
        <>
          <div role="group" aria-label="Días disponibles" className="mt-3 flex flex-wrap gap-2">
            {dias.map((clave) => (
              <button
                key={clave}
                type="button"
                aria-pressed={dia === clave}
                className={`${CHOICE} ${dia === clave ? CHOICE_ON : CHOICE_OFF}`}
                onClick={() => {
                  setDia(clave);
                  setElegido(null);
                }}
              >
                {formatDayLabel(clave)}
              </button>
            ))}
          </div>
          {dia !== null && (
            <div role="group" aria-label={`Horarios del ${formatDayLabel(dia)}`} className="mt-3 flex flex-wrap gap-2">
              {(porDia.get(dia) ?? []).map((slot) => {
                const esActual = sameInstant(slot.starts_at, actual);
                const hora = formatTime(new Date(slot.starts_at), tz);
                return (
                  <button
                    key={slot.starts_at}
                    type="button"
                    disabled={esActual}
                    aria-current={esActual ? "true" : undefined}
                    aria-pressed={elegido === slot.starts_at}
                    className={`${CHOICE} ${elegido === slot.starts_at ? CHOICE_ON : CHOICE_OFF} disabled:opacity-60`}
                    onClick={() => setElegido(slot.starts_at)}
                  >
                    {esActual ? `${hora} (horario actual)` : hora}
                  </button>
                );
              })}
            </div>
          )}
        </>
      )}
      <div className="mt-4 flex flex-col gap-2">
        {elegido !== null && (
          <button type="button" className={PRIMARY} disabled={pending} onClick={() => onSubmit(elegido)}>
            Confirmar {formatTime(new Date(elegido), tz)}
          </button>
        )}
        <button type="button" className={SECONDARY} onClick={onClose}>
          Volver sin cambios
        </button>
      </div>
    </section>
  );
}

export default ReschedulePanel;
