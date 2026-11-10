/**
 * Reportes y auditoría para administración (C-13, US-050/US-051; pestaña WhatsApp en C-10;
 * pestaña Piloto con las métricas de éxito en C-14).
 * Rango por defecto: el mes en curso en la zona de la clínica. Todo se calcula en el
 * backend desde la auditoría; esta pantalla solo presenta y descarga.
 */
import { useState } from "react";
import { useClinic } from "../../shared/api/queries";
import { Alert, PageTitle, SelectField, TextField } from "../../shared/ui";
import { useClock } from "../../shared/time/now";
import { dateKeyOf, zonedDayRange } from "../../shared/time/zoned";
import type { DateRange } from "./api";
import {
  AbsenteeismPanel,
  AuditPanel,
  CancellationsPanel,
  DownloadButton,
  OccupancyPanel,
  WaitlistPanel,
  WhatsAppPanel
} from "./Panels";
import { PilotPanel } from "./PilotPanel";

type TabId =
  | "occupancy"
  | "absenteeism"
  | "cancellations"
  | "whatsapp"
  | "waitlist"
  | "pilot"
  | "audit";

const TABS: readonly { id: TabId; label: string }[] = [
  { id: "occupancy", label: "Ocupación" },
  { id: "absenteeism", label: "Ausentismo" },
  { id: "cancellations", label: "Cancelaciones" },
  { id: "whatsapp", label: "WhatsApp" },
  { id: "waitlist", label: "Lista de espera" },
  { id: "pilot", label: "Piloto" },
  { id: "audit", label: "Auditoría" }
];

function monthRange(today: string): DateRange {
  const [anio = 1970, mes = 1] = today.split("-").map(Number);
  const ultimo = new Date(Date.UTC(anio, mes, 0)).getUTCDate();
  const prefijo = `${String(anio).padStart(4, "0")}-${String(mes).padStart(2, "0")}`;
  return { from: `${prefijo}-01`, to: `${prefijo}-${String(ultimo).padStart(2, "0")}` };
}

function ReportsPage(): JSX.Element {
  const clinic = useClinic();
  const clock = useClock();
  const [tab, setTab] = useState<TabId>("occupancy");
  const [formato, setFormato] = useState<"csv" | "json">("csv");
  const [edicion, setEdicion] = useState<Partial<DateRange>>({});

  if (clinic.isError) {
    return (
      <section>
        <PageTitle>Reportes</PageTitle>
        <Alert>No se pudo cargar la clínica. Volvé a intentar en unos minutos.</Alert>
      </section>
    );
  }
  if (clinic.data === undefined) {
    return (
      <section>
        <PageTitle>Reportes</PageTitle>
        <p role="status">Cargando…</p>
      </section>
    );
  }

  const tz = clinic.data.timezone;
  const porDefecto = monthRange(dateKeyOf(clock(), tz));
  const desde = edicion.from ?? porDefecto.from;
  const hasta = edicion.to ?? porDefecto.to;
  const rangoValido = desde !== "" && hasta !== "" && desde <= hasta;
  const range: DateRange = { from: desde, to: hasta };

  return (
    <section className="space-y-4">
      <PageTitle>Reportes</PageTitle>

      <div className="flex flex-wrap items-end gap-3 rounded bg-white p-3 shadow-sm">
        <TextField
          label="Desde"
          type="date"
          value={desde}
          onChange={(e) => setEdicion((prev) => ({ ...prev, from: e.target.value }))}
        />
        <TextField
          label="Hasta"
          type="date"
          value={hasta}
          onChange={(e) => setEdicion((prev) => ({ ...prev, to: e.target.value }))}
        />
        <SelectField
          label="Formato de la exportación"
          value={formato}
          onChange={(e) => setFormato(e.target.value as "csv" | "json")}
        >
          <option value="csv">CSV</option>
          <option value="json">JSON</option>
        </SelectField>
        <DownloadButton
          label="Exportar todos mis datos"
          path="/api/exports/full"
          query={{ format: formato }}
          filename={`export-completo.zip`}
        />
      </div>

      {!rangoValido && (
        <Alert>La fecha inicial debe ser anterior o igual a la final.</Alert>
      )}

      <div role="tablist" aria-label="Reportes" className="flex flex-wrap gap-1">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={tab === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => setTab(t.id)}
            className={`rounded px-3 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-dental-600 ${
              tab === t.id ? "bg-dental-600 text-white" : "bg-white hover:bg-dental-50"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {rangoValido && (
        <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>
          {tab === "occupancy" && <OccupancyPanel range={range} />}
          {tab === "absenteeism" && <AbsenteeismPanel range={range} />}
          {tab === "cancellations" && <CancellationsPanel range={range} />}
          {tab === "whatsapp" && <WhatsAppPanel range={range} />}
          {tab === "waitlist" && <WaitlistPanel range={range} />}
          {tab === "pilot" && <PilotPanel range={range} />}
          {tab === "audit" && (
            <AuditPanel
              range={range}
              tz={tz}
              from={zonedDayRange(range.from, tz).from.toISOString()}
              to={zonedDayRange(range.to, tz).to.toISOString()}
            />
          )}
        </div>
      )}
    </section>
  );
}

export default ReportsPage;
