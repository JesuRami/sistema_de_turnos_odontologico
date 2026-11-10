/**
 * Métricas de éxito del piloto (C-14, D9; KB `01` §Métricas). Todo se calcula en el backend sobre
 * la auditoría; acá se presenta cada métrica con su meta y su base (numerador/denominador).
 */
import { useState } from "react";
import type { PilotMetric } from "../../shared/api/types";
import { Alert, TextField } from "../../shared/ui";
import { Skeleton } from "../../shared/ui/Skeleton";
import { usePilotReport, type DateRange } from "./api";
import { describeError, DownloadButton } from "./Panels";

const ETIQUETA: Record<string, string> = {
  no_show_rate: "Ausentismo (no vino)",
  confirmation_before_24h_rate: "Confirmados antes de T−24 h",
  waitlist_recovery_rate: "Huecos recuperados por lista de espera",
  online_share: "Turnos reservados online"
};

const META: Record<string, string> = {
  no_show_rate: "−20 % vs. línea base",
  confirmation_before_24h_rate: "≥ 60 %",
  waitlist_recovery_rate: "≥ 10 %",
  online_share: "≥ 30 %"
};

function pct(valor: number | null): string {
  return valor === null ? "—" : `${(valor * 100).toLocaleString("es-AR", { maximumFractionDigits: 1 })} %`;
}

function Estado({ met }: { met: boolean | null }): JSX.Element {
  if (met === null) {
    return <span className="rounded bg-slate-100 px-1.5 text-xs text-slate-700">Sin datos suficientes</span>;
  }
  return met ? (
    <span className="rounded bg-emerald-100 px-1.5 text-xs text-emerald-900">Cumple</span>
  ) : (
    <span className="rounded bg-amber-100 px-1.5 text-xs text-amber-900">No cumple</span>
  );
}

function Fila({ m }: { m: PilotMetric }): JSX.Element {
  const detalle =
    m.key === "no_show_rate" && m.delta_vs_baseline_pct !== null && m.delta_vs_baseline_pct !== undefined
      ? ` (${m.delta_vs_baseline_pct > 0 ? "+" : ""}${m.delta_vs_baseline_pct.toLocaleString("es-AR")} % vs. base)`
      : "";
  return (
    <tr className="border-t border-dental-600/10">
      <th scope="row" className="px-2 py-1 font-normal">{ETIQUETA[m.key] ?? m.key}</th>
      <td className="px-2 py-1">{`${pct(m.value)}${detalle}`}</td>
      <td className="px-2 py-1">{`${m.numerator} / ${m.denominator}`}</td>
      <td className="px-2 py-1">{META[m.key] ?? "—"}</td>
      <td className="px-2 py-1">
        <Estado met={m.met} />
      </td>
    </tr>
  );
}

export function PilotPanel({ range }: { range: DateRange }): JSX.Element {
  const [base, setBase] = useState("");
 const numero = Number(String(base ?? "").replace(",", "."));
 const baseline = (String(base ?? "").trim() !== "" && Number.isFinite(numero) && numero > 0 && numero <= 100) ? numero : null;
 const informe = usePilotReport(range, baseline);
  const query: Record<string, string> = { ...range, format: "csv" };
  if (baseline !== null) {
    query.baseline_no_show_pct = String(baseline);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <TextField
          label="Ausentismo previo de la clínica (%)"
          type="number"
          min={0}
          max={100}
          step="0.1"
          hint="Línea base para medir la meta de −20 %. Dejalo vacío si no la tenés."
          value={base}
          onChange={(e) => setBase(e.target.value)}
        />
        <DownloadButton
          label="Descargar CSV"
          path="/api/reports/pilot"
          query={query}
          filename={`piloto-${range.from}-${range.to}.csv`}
        />
      </div>
      {base.trim() !== "" && baseline === null && (
        <Alert>La línea base tiene que ser un porcentaje mayor que 0 y hasta 100.</Alert>
      )}
      {informe.isPending && <Skeleton label="Cargando métricas del piloto…" rows={5} />}
      {informe.isError && <Alert>{describeError(informe.error)}</Alert>}
      {informe.data !== undefined && (
        <>
          {informe.data.overlaps_ok ? (
            <Alert tone="success">Integridad de agenda: 0 turnos superpuestos en el período.</Alert>
          ) : (
            <Alert>
              {`Integridad de agenda: ${informe.data.overlaps} pares de turnos superpuestos. Avisá a soporte: la base debería impedirlo.`}
            </Alert>
          )}
          <div className="overflow-x-auto rounded bg-white p-2 shadow-sm">
            <table className="w-full min-w-[32rem] text-left text-sm">
              <caption className="sr-only">Métricas de éxito del piloto</caption>
              <thead>
                <tr>
                  <th scope="col" className="px-2 py-1 font-medium">Métrica</th>
                  <th scope="col" className="px-2 py-1 font-medium">Valor</th>
                  <th scope="col" className="px-2 py-1 font-medium">Base</th>
                  <th scope="col" className="px-2 py-1 font-medium">Meta</th>
                  <th scope="col" className="px-2 py-1 font-medium">Estado</th>
                </tr>
              </thead>
              <tbody>
                <Fila m={informe.data.no_show} />
                <Fila m={informe.data.confirmation_before_24h} />
                <Fila m={informe.data.waitlist_recovery} />
                <Fila m={informe.data.online_share} />
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
