/**
 * Agenda del día imprimible (C-14, D11; SU-06). Mitigación mínima de cortes de internet: recepción
 * imprime la agenda al abrir y, si se cae la red, sigue con el papel. Por sillón, en la zona de la
 * clínica, sin cancelados. No se guarda nada en el navegador (regla 13): el papel queda en la
 * clínica como cualquier agenda impresa.
 */
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAppointments, useChairs, useClinic, useProfessionals } from "../../shared/api/queries";
import type { Appointment } from "../../shared/api/types";
import { useClock } from "../../shared/time/now";
import { dateKeyOf, formatDayLabel, formatTime, zonedRange } from "../../shared/time/zoned";
import { Alert, Button } from "../../shared/ui";
import { AgendaSkeleton } from "../../shared/ui/Skeleton";
import { ORIGIN_LABEL, STATUS_LABEL } from "./labels";

const DIA_RE = /^\d{4}-\d{2}-\d{2}$/;

function PrintableDay(): JSX.Element {
  const [params] = useSearchParams();
  const clock = useClock();
  const clinic = useClinic();
  const chairs = useChairs();
  const professionals = useProfessionals();
  const tz = clinic.data?.timezone ?? null;
  const pedido = params.get("dia") ?? "";
  const dia = DIA_RE.test(pedido) ? pedido : tz !== null ? dateKeyOf(clock(), tz) : null;
  const range = useMemo(() => (tz !== null && dia !== null ? zonedRange(dia, 1, tz) : null), [tz, dia]);
  const appointments = useAppointments(range);

  const porSillon = useMemo(() => {
    const vigentes = (appointments.data ?? [])
      .filter((a) => a.status !== "cancelled")
      .sort((a, b) => a.starts_at.localeCompare(b.starts_at));
    const grupos = new Map<string, Appointment[]>();
    for (const turno of vigentes) {
      grupos.set(turno.chair_id, [...(grupos.get(turno.chair_id) ?? []), turno]);
    }
    return grupos;
  }, [appointments.data]);

  if (clinic.isError || appointments.isError) {
    return <Alert>No se pudo cargar la agenda para imprimir. Reintentá cuando vuelva la conexión.</Alert>;
  }
  if (tz === null || dia === null || appointments.data === undefined) {
    return <AgendaSkeleton label="Preparando la agenda para imprimir…" />;
  }

  const nombreProfesional = new Map((professionals.data ?? []).map((p) => [p.id, p.display_name]));
  const sillones = (chairs.data ?? []).filter((c) => porSillon.has(c.id) || c.active);

  return (
    <section aria-label="Agenda del día para imprimir" className="mx-auto max-w-4xl text-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 print:hidden">
        <Link to="/" className="underline">
          Volver a la agenda
        </Link>
        <Button onClick={() => window.print()}>Imprimir</Button>
      </div>
      <h1 className="text-xl font-semibold">{`Agenda del ${formatDayLabel(dia)}`}</h1>
      <p className="mb-4 text-xs opacity-80">
        {`${clinic.data?.name ?? ""} · Generada a las ${formatTime(clock(), tz)} (hora de la clínica). Los cambios posteriores no figuran.`}
      </p>
      {sillones.length === 0 && <p>No hay sillones activos.</p>}
      {sillones.map((sillon) => {
        const turnos = porSillon.get(sillon.id) ?? [];
        return (
          <div key={sillon.id} className="mb-6 break-inside-avoid">
            <h2 className="mb-1 text-base font-semibold">{sillon.name}</h2>
            {turnos.length === 0 ? (
              <p className="italic opacity-70">Sin turnos.</p>
            ) : (
              <table className="w-full border-collapse text-left">
                <caption className="sr-only">{`Turnos de ${sillon.name}`}</caption>
                <thead>
                  <tr className="border-b border-black/30">
                    <th scope="col" className="py-1 pr-2">Hora</th>
                    <th scope="col" className="py-1 pr-2">Paciente</th>
                    <th scope="col" className="py-1 pr-2">Teléfono</th>
                    <th scope="col" className="py-1 pr-2">Profesional</th>
                    <th scope="col" className="py-1 pr-2">Estado</th>
                    <th scope="col" className="py-1 pr-2">Asistió</th>
                  </tr>
                </thead>
                <tbody>
                  {turnos.map((t) => (
                    <tr key={t.id} className="border-b border-black/10 align-top">
                      <td className="py-1 pr-2 whitespace-nowrap">
                        {`${formatTime(new Date(t.starts_at), tz)}–${formatTime(new Date(t.ends_at), tz)}`}
                      </td>
                      <td className="py-1 pr-2">
                        {t.patient.full_name}
                        {t.is_overbooking ? " (sobreturno)" : ""}
                        <span className="block text-xs opacity-70">{ORIGIN_LABEL[t.origin]}</span>
                      </td>
                      <td className="py-1 pr-2 whitespace-nowrap">{t.patient.phone_e164 ?? "—"}</td>
                      <td className="py-1 pr-2">{nombreProfesional.get(t.professional_id) ?? "—"}</td>
                      <td className="py-1 pr-2">{STATUS_LABEL[t.status]}</td>
                      <td className="py-1 pr-2" aria-label="Casilla para marcar a mano">
                        ☐
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        );
      })}
    </section>
  );
}

export default PrintableDay;
