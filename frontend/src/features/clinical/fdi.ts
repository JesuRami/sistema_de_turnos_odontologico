/** Numeración FDI (ISO 3950) y caras, espejo de `backend/app/modules/clinical/fdi.py` (C-15). */

export type Dentition = "permanent" | "deciduous";
export type Surface = "M" | "D" | "O" | "V" | "L" | "W";

export const SURFACES: readonly Surface[] = ["M", "D", "O", "V", "L", "W"];

const range = (desde: number, hasta: number): number[] =>
  Array.from({ length: hasta - desde + 1 }, (_, i) => desde + i);

export const PERMANENT_TEETH: readonly number[] = [1, 2, 3, 4].flatMap((q) =>
  range(1, 8).map((p) => q * 10 + p)
);
export const DECIDUOUS_TEETH: readonly number[] = [5, 6, 7, 8].flatMap((q) =>
  range(1, 5).map((p) => q * 10 + p)
);

export function teethOf(dentition: Dentition): readonly number[] {
  return dentition === "permanent" ? PERMANENT_TEETH : DECIDUOUS_TEETH;
}

export function isValidTooth(tooth: number): boolean {
  return PERMANENT_TEETH.includes(tooth) || DECIDUOUS_TEETH.includes(tooth);
}

const LABELS: Record<Surface, string> = {
  M: "mesial",
  D: "distal",
  O: "oclusal",
  V: "vestibular",
  L: "lingual",
  W: "pieza completa"
};

/** `O` es incisal en incisivos y caninos (posiciones 1–3). */
export function surfaceLabel(tooth: number, surface: Surface): string {
  if (surface === "O" && tooth % 10 <= 3) {
    return "incisal";
  }
  return LABELS[surface];
}

/** Partes de ≤ `size` (los lotes del odontograma son de 32 como máximo). */
export function chunk<T>(items: readonly T[], size: number): T[][] {
  const partes: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    partes.push(items.slice(i, i + size));
  }
  return partes;
}
