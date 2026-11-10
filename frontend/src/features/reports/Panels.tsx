/** Paneles de reportes y auditoría (C-13). Cada uno pide sus datos y ofrece su CSV. */
import { useState } from "react";
import { ApiError } from "../../shared/api/client";
import type { AppointmentEventKind, ReportGroupBy } from "../../shared/api/types";
import { Alert, Button, SelectField, TextField } from "../../shared/ui";
import {
  useAbsenteeism,
  useAudit,
  useCancellations,
  useOccupancy,
  useWaitlistReport,
  useWhatsAppReport,
  type DateRange
} from "./api";
import { downloadFile } from "./download";
import {
  CHANNEL_LABEL,
  EVENT_LABEL,
  formatInstant,
  hours,
  percent,
  rate,
  REASON_LABEL,
  stepLabel,
  usd
} from "./format";

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.detail === "invalid_range") {
      return "El rango de fechas no es válido: la fecha inicial debe ser anterior o igual a la final.";
    }
    if (error.detail === "range_too_large") {
      return "El rango es demasiado largo: el máximo es de un año. Elegí un período más corto.";
    }
    if (error.status === 403) {
      return "No tenés permiso para ver este reporte.";
    }
  }
  return "No se pudo cargar. Revisá tu conexión y volvé a intentar en unos minutos.";
}

function Loading(): JSX.Element {
  return <p role="status">Cargando…</p>;
}

function Empty({ children }: { children: string }): JSX.Element {
  return <p className="rounded bg-white p-4 text-sm shadow-sm">{children}</p>;
}

export function DownloadButton({
  label,
  path,
  query,
  filename
}: {
  label: string;
  path: string;
  query: Record<string, string>;
  filename: string;
}): JSX.Element {
  const [pendiente, setPendiente] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function descargar(): Promise<void> {
    setPendiente(true);
    setError(null);
    try {
      await downloadFile(path, query, filename);
    } catch (e) {
      setError(describeError(e));
    } finally {
      setPendiente(false);
    }
  }

  return (
    <div>
      <Button variant="secondary" disabled={pendiente} onClick={() => void descargar()}>
        {pendiente ? "Descargando…" : label}
      </Button>
      {error !== null && <Alert>{error}</Alert>}
    </div>
  );
}

const TABLA = "w-full min-w-[32rem] text-left text-sm";
const TH = "px-2 py-1 font-medium";
const TD = "px-2 py-1";

export function OccupancyPanel({ range }: { range: DateRange }): JSX.Element {
  const [groupBy, setGroupBy] = useState<ReportGroupBy>("professional");
  const informe = useOccupancy(range, groupBy);
  const etiqueta = groupBy === "professional" ? "Profesional" : "Sillón";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <SelectField
          label="Agrupar por"
          value={groupBy}
          onChange={(e) => setGroupBy(e.target.value as ReportGroupBy)}
        >
          <option value="professional">Profesional</option>
          <option value="chair">Sillón</option>
        </SelectField>
        <DownloadButton
          label="Descargar CSV"
          path="/api/reports/occupancy"
          query={{ ...range, group_by: groupBy, format: "csv" }}
          filename={`ocupacion-${groupBy}-${range.from}-${range.to}.csv`}
        />
      </div>
      <Alert tone="info">
        La capacidad se calcula con el horario vigente de la agenda, no con el que regía en esas
        fechas.
      </Alert>
      {informe.isPending && <Loading />}
      {informe.isError && <Alert>{describeError(informe.error)}</Alert>}
      {informe.data !== undefined &&
        (informe.data.rows.length === 0 ? (
          <Empty>No hay turnos ni horarios en este período.</Empty>
        ) : (
          <div className="overflow-x-auto rounded bg-white p-2 shadow-sm">
            <table className={TABLA}>
              <caption className="sr-only">Ocupación por {etiqueta.toLowerCase()}</caption>
              <thead>
                <tr>
                  <th scope="col" className={TH}>{etiqueta}</th>
                  <th scope="col" className={TH}>Turnos</th>
                  <th scope="col" className={TH}>Sobreturnos</th>
                  <th scope="col" className={TH}>Reservado</th>
                  <th scope="col" className={TH}>Capacidad</th>
                  <th scope="col" className={TH}>Ocupación</th>
                </tr>
              </thead>
              <tbody>
                {informe.data.rows.map((fila) => (
                  <tr key={fila.resource_id} className="border-t border-dental-600/10">
                    <th scope="row" className={`${TD} font-normal`}>{fila.resource_name}</th>
                    <td className={TD}>{fila.appointments}</td>
                    <td className={TD}>{fila.overbookings}</td>
                    <td className={TD}>{hours(fila.booked_min)}</td>
                    <td className={TD}>{hours(fila.capacity_min)}</td>
                    <td className={TD}>{percent(fila.occupancy_pct)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-dental-600/30 font-medium">
                  <th scope="row" className={TD}>Total</th>
                  <td className={TD}>{informe.data.totals.appointments}</td>
                  <td className={TD}>{informe.data.totals.overbookings}</td>
                  <td className={TD}>{hours(informe.data.totals.booked_min)}</td>
                  <td className={TD}>{hours(informe.data.totals.capacity_min)}</td>
                  <td className={TD}>{percent(informe.data.totals.occupancy_pct)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        ))}
    </div>
  );
}

export function AbsenteeismPanel({ range }: { range: DateRange }): JSX.Element {
  const informe = useAbsenteeism(range);
  return (
    <div className="space-y-3">
      <DownloadButton
        label="Descargar CSV"
        path="/api/reports/absenteeism"
        query={{ ...range, format: "csv" }}
        filename={`ausentismo-${range.from}-${range.to}.csv`}
      />
      <Alert tone="info">
        «No vino» (sin aviso), «Ausente con aviso» y «Cancelación tardía» se cuentan por separado.
        Las cancelaciones con anticipación suficiente no entran en el cálculo.
      </Alert>
      {informe.isPending && <Loading />}
      {informe.isError && <Alert>{describeError(informe.error)}</Alert>}
      {informe.data !== undefined &&
        (informe.data.rows.length === 0 ? (
          <Empty>No hay turnos con desenlace en este período.</Empty>
        ) : (
          <div className="overflow-x-auto rounded bg-white p-2 shadow-sm">
            <table className={TABLA}>
              <caption className="sr-only">Ausentismo por profesional</caption>
              <thead>
                <tr>
                  <th scope="col" className={TH}>Profesional</th>
                  <th scope="col" className={TH}>Asistieron</th>
                  <th scope="col" className={TH}>Ausente con aviso</th>
                  <th scope="col" className={TH}>No vino</th>
                  <th scope="col" className={TH}>Cancelación tardía</th>
                  <th scope="col" className={TH}>Tasa «no vino»</th>
                </tr>
              </thead>
              <tbody>
                {informe.data.rows.map((f) => (
                  <tr key={f.professional_id} className="border-t border-dental-600/10">
                    <th scope="row" className={`${TD} font-normal`}>{f.professional_name}</th>
                    <td className={TD}>{f.present}</td>
                    <td className={TD}>{f.absent}</td>
                    <td className={TD}>{f.no_show}</td>
                    <td className={TD}>{f.late_cancellations}</td>
                    <td className={TD}>{rate(f.no_show_rate)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-dental-600/30 font-medium">
                  <th scope="row" className={TD}>Total</th>
                  <td className={TD}>{informe.data.totals.present}</td>
                  <td className={TD}>{informe.data.totals.absent}</td>
                  <td className={TD}>{informe.data.totals.no_show}</td>
                  <td className={TD}>{informe.data.totals.late_cancellations}</td>
                  <td className={TD}>{rate(informe.data.totals.no_show_rate)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        ))}
    </div>
  );
}

export function CancellationsPanel({ range }: { range: DateRange }): JSX.Element {
  const informe = useCancellations(range);
  return (
    <div className="space-y-3">
      <DownloadButton
        label="Descargar CSV"
        path="/api/reports/cancellations"
        query={{ ...range, format: "csv" }}
        filename={`cancelaciones-${range.from}-${range.to}.csv`}
      />
      {informe.isPending && <Loading />}
      {informe.isError && <Alert>{describeError(informe.error)}</Alert>}
      {informe.data !== undefined &&
        (informe.data.total === 0 ? (
          <Empty>No hubo cancelaciones en este período.</Empty>
        ) : (
          <div className="overflow-x-auto rounded bg-white p-2 shadow-sm">
            <table className={TABLA}>
              <caption className="sr-only">Cancelaciones por motivo</caption>
              <thead>
                <tr>
                  <th scope="col" className={TH}>Motivo</th>
                  <th scope="col" className={TH}>Total</th>
                  <th scope="col" className={TH}>Tardías</th>
                  <th scope="col" className={TH}>Con anticipación</th>
                </tr>
              </thead>
              <tbody>
                {informe.data.rows.map((f) => (
                  <tr key={f.reason} className="border-t border-dental-600/10">
                    <th scope="row" className={`${TD} font-normal`}>
                      {REASON_LABEL[f.reason] ?? f.reason}
                    </th>
                    <td className={TD}>{f.total}</td>
                    <td className={TD}>{f.late}</td>
                    <td className={TD}>{f.in_window}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </div>
  );
}

export function WhatsAppPanel({ range }: { range: DateRange }): JSX.Element {
  const informe = useWhatsAppReport(range);
  return (
    <div className="space-y-3">
      <DownloadButton
        label="Descargar CSV"
        path="/api/reports/whatsapp"
        query={{ ...range, format: "csv" }}
        filename={`whatsapp-${range.from}-${range.to}.csv`}
      />
      <Alert tone="info">
        Cuenta los mensajes enviados en el período y lo que Meta informó después (entregado, leído
        o fallido). El costo es el estimado por mensaje configurado para la clínica.
      </Alert>
      {informe.isPending && <Loading />}
      {informe.isError && <Alert>{describeError(informe.error)}</Alert>}
      {informe.data !== undefined &&
        (informe.data.totals.sent === 0 ? (
          <Empty>No se enviaron mensajes de recordatorio en este período.</Empty>
        ) : (
          <div className="overflow-x-auto rounded bg-white p-2 shadow-sm">
            <table className={TABLA}>
              <caption className="sr-only">Mensajes por paso y canal</caption>
              <thead>
                <tr>
                  <th scope="col" className={TH}>Paso</th>
                  <th scope="col" className={TH}>Canal</th>
                  <th scope="col" className={TH}>Enviados</th>
                  <th scope="col" className={TH}>Entregados</th>
                  <th scope="col" className={TH}>Leídos</th>
                  <th scope="col" className={TH}>Fallidos</th>
                  <th scope="col" className={TH}>Costo (USD)</th>
                </tr>
              </thead>
              <tbody>
                {informe.data.rows.map((f) => (
                  <tr key={`${f.step}-${f.channel}`} className="border-t border-dental-600/10">
                    <th scope="row" className={`${TD} font-normal`}>{stepLabel(f.step)}</th>
                    <td className={TD}>{CHANNEL_LABEL[f.channel] ?? f.channel}</td>
                    <td className={TD}>{f.sent}</td>
                    <td className={TD}>{f.delivered}</td>
                    <td className={TD}>{f.read}</td>
                    <td className={TD}>{f.failed}</td>
                    <td className={TD}>{usd(f.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-dental-600/30 font-medium">
                  <th scope="row" colSpan={2} className={TD}>Total</th>
                  <td className={TD}>{informe.data.totals.sent}</td>
                  <td className={TD}>{informe.data.totals.delivered}</td>
                  <td className={TD}>{informe.data.totals.read}</td>
                  <td className={TD}>{informe.data.totals.failed}</td>
                  <td className={TD}>{usd(informe.data.totals.cost_usd)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        ))}
    </div>
  );
}

export function AuditPanel({
  range,
  from,
  to,
  tz
}: {
  range: DateRange;
  from: string;
  to: string;
  tz: string;
}): JSX.Element {
  const [evento, setEvento] = useState<AppointmentEventKind | "">("");
  const [turno, setTurno] = useState("");
  const consulta = useAudit({ from, to, event: evento, appointmentId: turno.trim() });
  const eventos = consulta.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <SelectField
          label="Tipo de evento"
          value={evento}
          onChange={(e) => setEvento(e.target.value as AppointmentEventKind | "")}
        >
          <option value="">Todos</option>
          {Object.entries(EVENT_LABEL).map(([valor, texto]) => (
            <option key={valor} value={valor}>
              {texto}
            </option>
          ))}
        </SelectField>
        <TextField
          label="Turno (identificador)"
          value={turno}
          onChange={(e) => setTurno(e.target.value)}
        />
      </div>
      <p className="text-xs opacity-70">
        Eventos entre el {range.from} y el {range.to}, en la hora de la clínica.
      </p>
      {consulta.isPending && <Loading />}
      {consulta.isError && <Alert>{describeError(consulta.error)}</Alert>}
      {consulta.data !== undefined &&
        (eventos.length === 0 ? (
          <Empty>No hay eventos con estos filtros.</Empty>
        ) : (
          <div className="overflow-x-auto rounded bg-white p-2 shadow-sm">
            <table className={TABLA}>
              <caption className="sr-only">Auditoría de turnos</caption>
              <thead>
                <tr>
                  <th scope="col" className={TH}>Fecha y hora</th>
                  <th scope="col" className={TH}>Evento</th>
                  <th scope="col" className={TH}>Estado</th>
                  <th scope="col" className={TH}>Quién</th>
                  <th scope="col" className={TH}>Turno</th>
                </tr>
              </thead>
              <tbody>
                {eventos.map((e) => (
                  <tr key={e.id} className="border-t border-dental-600/10">
                    <td className={TD}>{formatInstant(e.created_at, tz)}</td>
                    <td className={TD}>{EVENT_LABEL[e.event] ?? e.event}</td>
                    <td className={TD}>
                      {e.from_status ?? "—"} → {e.to_status ?? "—"}
                    </td>
                    <td className={TD}>
                      {e.actor_type === "user" && e.actor_user_id !== null
                        ? `Usuario ${e.actor_user_id.slice(0, 8)}`
                        : e.actor_type === "system"
                          ? "Sistema"
                          : "Paciente"}
                    </td>
                    <td className={TD}>{e.appointment_id.slice(0, 8)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      {consulta.hasNextPage && (
        <Button
          variant="secondary"
          disabled={consulta.isFetchingNextPage}
          onClick={() => void consulta.fetchNextPage()}
        >
          {consulta.isFetchingNextPage ? "Cargando…" : "Cargar más"}
        </Button>
      )}
    </div>
  );
}

function tasa(valor: number | null): string {
  return valor === null ? "—" : `${valor.toLocaleString("es-AR")} %`;
}

/** Conversión de la lista de espera (C-12, US-050): ofertas y resultado por profesional. */
export function WaitlistPanel({ range }: { range: DateRange }): JSX.Element {
  const informe = useWaitlistReport(range);
  const columnas = [
    "Creadas",
    "Automáticas",
    "Manuales",
    "Aceptadas",
    "Rechazadas",
    "Vencidas",
    "Cerradas",
    "Conversión"
  ];
  return (
    <div className="space-y-3">
      <DownloadButton
        label="Descargar CSV"
        path="/api/reports/waitlist"
        query={{ ...range, format: "csv" }}
        filename={`lista-de-espera-${range.from}-${range.to}.csv`}
      />
      <Alert tone="info">
        Cuenta las ofertas creadas en el período y cómo terminaron. La conversión es aceptadas sobre
        creadas; una oferta todavía pendiente solo cuenta como creada.
      </Alert>
      {informe.isPending && <Loading />}
      {informe.isError && <Alert>{describeError(informe.error)}</Alert>}
      {informe.data !== undefined &&
        (informe.data.rows.length === 0 ? (
          <Empty>No hay profesionales activos para mostrar.</Empty>
        ) : (
          <div className="overflow-x-auto rounded bg-white p-2 shadow-sm">
            <table className={TABLA}>
              <caption className="sr-only">Conversión de la lista de espera</caption>
              <thead>
                <tr>
                  <th scope="col" className={TH}>Profesional</th>
                  {columnas.map((c) => (
                    <th key={c} scope="col" className={TH}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {informe.data.rows.map((f) => (
                  <tr key={f.professional_id} className="border-t border-dental-600/10">
                    <th scope="row" className={`${TD} font-normal`}>{f.professional_name}</th>
                    <td className={TD}>{f.created}</td>
                    <td className={TD}>{f.auto}</td>
                    <td className={TD}>{f.manual}</td>
                    <td className={TD}>{f.accepted}</td>
                    <td className={TD}>{f.declined}</td>
                    <td className={TD}>{f.expired}</td>
                    <td className={TD}>{f.cancelled}</td>
                    <td className={TD}>{tasa(f.conversion_pct)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-dental-600/30 font-medium">
                  <th scope="row" className={TD}>Total</th>
                  <td className={TD}>{informe.data.totals.created}</td>
                  <td className={TD}>{informe.data.totals.auto}</td>
                  <td className={TD}>{informe.data.totals.manual}</td>
                  <td className={TD}>{informe.data.totals.accepted}</td>
                  <td className={TD}>{informe.data.totals.declined}</td>
                  <td className={TD}>{informe.data.totals.expired}</td>
                  <td className={TD}>{informe.data.totals.cancelled}</td>
                  <td className={TD}>{tasa(informe.data.totals.conversion_pct)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        ))}
    </div>
  );
}
