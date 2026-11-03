/**
 * Layout puro de la grilla de agenda (D5): rango visible, posiciones por minuto,
 * carriles para lo que se solapa y distintivos. Sin React ni red.
 */
import type { AppointmentStatus, Professional, ScheduleRule } from "../../shared/api/types";
import { minutesOfDay, weekdayOf, type DateKey } from "../../shared/time/zoned";

export interface VisibleRange {
  startMin: number;
  endMin: number;
}

export const DEFAULT_RANGE: VisibleRange = { startMin: 8 * 60, endMin: 20 * 60 };
export const SLOT_MIN = 15;

const toMinutes = (hhmmss: string): number => {
  const [h, m] = hhmmss.split(":").map(Number);
  return (h ?? 0) * 60 + (m ?? 0);
};

function ruleApplies(rule: ScheduleRule, day: DateKey): boolean {
  return (
    rule.active &&
    rule.weekday === weekdayOf(day) &&
    rule.valid_from <= day &&
    (rule.valid_to === null || day <= rule.valid_to)
  );
}

/** Mínimo inicio y máximo fin (redondeados a la hora) de las reglas de esos días. */
export function visibleRange(rules: readonly ScheduleRule[], days: readonly DateKey[]): VisibleRange {
  const aplicables = rules.filter((r) => days.some((d) => ruleApplies(r, d)));
  if (aplicables.length === 0) {
    return DEFAULT_RANGE;
  }
  const inicio = Math.min(...aplicables.map((r) => toMinutes(r.start_time)));
  const fin = Math.max(...aplicables.map((r) => toMinutes(r.end_time)));
  return { startMin: Math.floor(inicio / 60) * 60, endMin: Math.ceil(fin / 60) * 60 };
}

export interface GridItem {
  id: string;
  start: Date;
  end: Date;
  column: string;
}

export interface PlacedItem {
  id: string;
  column: string;
  /** Minutos desde el inicio visible. */
  top: number;
  height: number;
  lane: number;
  lanes: number;
}

/** Posiciona items por columna; los que se solapan se reparten en carriles. */
export function layoutItems(
  items: readonly GridItem[],
  range: VisibleRange,
  tz: string
): PlacedItem[] {
  const porColumna = new Map<string, { id: string; top: number; bottom: number }[]>();
  for (const item of items) {
    const inicio = minutesOfDay(item.start, tz);
    const duracion = Math.max(1, Math.round((item.end.getTime() - item.start.getTime()) / 60000));
    const top = Math.max(inicio, range.startMin);
    const bottom = Math.min(inicio + duracion, range.endMin);
    if (bottom <= top) {
      continue;
    }
    const lista = porColumna.get(item.column) ?? [];
    lista.push({ id: item.id, top: top - range.startMin, bottom: bottom - range.startMin });
    porColumna.set(item.column, lista);
  }

  const resultado: PlacedItem[] = [];
  for (const [column, lista] of porColumna) {
    lista.sort((a, b) => a.top - b.top || b.bottom - a.bottom || a.id.localeCompare(b.id));
    // Clusters de items que se solapan transitivamente: comparten cantidad de carriles.
    let cluster: { id: string; top: number; bottom: number; lane: number }[] = [];
    let finCluster = -1;
    const cerrar = (): void => {
      const lanes = Math.max(...cluster.map((c) => c.lane)) + 1;
      for (const c of cluster) {
        resultado.push({ id: c.id, column, top: c.top, height: c.bottom - c.top, lane: c.lane, lanes });
      }
      cluster = [];
    };
    for (const item of lista) {
      if (cluster.length > 0 && item.top >= finCluster) {
        cerrar();
      }
      const ocupados = new Set(cluster.filter((c) => c.bottom > item.top).map((c) => c.lane));
      let lane = 0;
      while (ocupados.has(lane)) {
        lane += 1;
      }
      cluster.push({ ...item, lane });
      finCluster = Math.max(finCluster, item.bottom);
    }
    if (cluster.length > 0) {
      cerrar();
    }
  }
  return resultado;
}

const DIA_MS = 24 * 60 * 60 * 1000;

/** Pendiente sin confirmar que empieza en menos de 24 h (Flujo 4 paso 1). */
export function isPendingSoon(status: AppointmentStatus, start: Date, now: Date): boolean {
  const falta = start.getTime() - now.getTime();
  return status === "pending" && falta > 0 && falta < DIA_MS;
}

const PALETA = ["#2563eb", "#059669", "#d97706", "#7c3aed", "#db2777", "#0891b2", "#65a30d", "#dc2626"];

/** Color del profesional, o uno estable derivado de su id. */
export function colorFor(professional: Pick<Professional, "id" | "color">): string {
  if (professional.color !== null) {
    return professional.color;
  }
  let hash = 0;
  for (const ch of professional.id) {
    hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  }
  return PALETA[hash % PALETA.length] ?? "#2563eb";
}
