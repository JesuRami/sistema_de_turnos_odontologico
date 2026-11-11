/**
 * Odontograma FDI accesible (C-15, D11): 32 piezas permanentes o 20 temporales, 5 caras + pieza
 * completa por pieza. Roving tabindex (flechas mueven el foco, Enter/Espacio elige la cara) y
 * etiqueta "Pieza 36, cara oclusal: caries". El estado se muestra con código corto además del
 * color. Los cambios quedan en un borrador en memoria hasta "Guardar".
 */
import { useMemo, useRef, useState, type KeyboardEvent } from "react";
import { SURFACES, surfaceLabel, teethOf, type Dentition, type Surface } from "./fdi";
import type { Condition, OdontogramEntry, ToothState } from "./types";

export type Draft = ReadonlyMap<string, string | null>;

export function draftKey(tooth: number, surface: Surface): string {
  return `${tooth}-${surface}`;
}

export function draftEntries(draft: Draft): OdontogramEntry[] {
  return [...draft.entries()].map(([clave, condition_id]) => {
    const [tooth, surface] = clave.split("-");
    return { tooth: Number(tooth), surface: surface as Surface, condition_id };
  });
}

interface Props {
  dentition: Dentition;
  teeth: readonly ToothState[];
  conditions: readonly Condition[];
  draft: Draft;
  onDraft: (tooth: number, surface: Surface, conditionId: string | null) => void;
}

function shortCode(code: string): string {
  return code.slice(0, 3).toUpperCase();
}

export default function Odontogram({ dentition, teeth, conditions, draft, onDraft }: Props): JSX.Element {
  const piezas = teethOf(dentition);
  const porPieza = useMemo(() => new Map(teeth.map((t) => [t.tooth, t])), [teeth]);
  const porId = useMemo(() => new Map(conditions.map((c) => [c.id, c])), [conditions]);
  const [foco, setFoco] = useState(0);
  const [elegida, setElegida] = useState<{ tooth: number; surface: Surface } | null>(null);
  const botones = useRef<(HTMLButtonElement | null)[]>([]);
  const total = piezas.length * SURFACES.length;

  function estadoDe(tooth: number, surface: Surface): Condition | null {
    const clave = draftKey(tooth, surface);
    if (draft.has(clave)) {
      const id = draft.get(clave);
      return id ? porId.get(id) ?? null : null;
    }
    const cara = porPieza.get(tooth)?.surfaces.find((s) => s.surface === surface);
    return cara?.condition_id ? porId.get(cara.condition_id) ?? null : null;
  }

  function mover(siguiente: number): void {
    const indice = (siguiente + total) % total;
    setFoco(indice);
    botones.current[indice]?.focus();
  }

  function onKey(event: KeyboardEvent<HTMLButtonElement>, indice: number): void {
    const salto: Record<string, number> = {
      ArrowRight: 1,
      ArrowLeft: -1,
      ArrowDown: SURFACES.length,
      ArrowUp: -SURFACES.length
    };
    if (event.key in salto) {
      event.preventDefault();
      mover(indice + salto[event.key]);
    }
  }

  const aplicables = elegida
    ? conditions.filter((c) => c.active && (c.scope === "tooth") === (elegida.surface === "W"))
    : [];

  return (
    <div>
      <div role="grid" aria-label={dentition === "permanent" ? "Dentición permanente" : "Dentición temporal"} className="grid grid-cols-4 gap-2 sm:grid-cols-8">
        {piezas.map((tooth, p) => (
          <div role="row" key={tooth} aria-label={`Pieza ${tooth}`} className="rounded border p-1 text-center">
            <span className="block text-xs font-semibold">{tooth}</span>
            {SURFACES.map((surface, s) => {
              const indice = p * SURFACES.length + s;
              const estado = estadoDe(tooth, surface);
              const nombre = `Pieza ${tooth}, cara ${surfaceLabel(tooth, surface)}: ${estado ? estado.label.toLowerCase() : "sin hallazgos"}`;
              return (
                <button
                  key={surface}
                  ref={(el) => {
                    botones.current[indice] = el;
                  }}
                  type="button"
                  role="gridcell"
                  aria-label={nombre}
                  aria-selected={elegida?.tooth === tooth && elegida.surface === surface}
                  tabIndex={indice === foco ? 0 : -1}
                  onKeyDown={(e) => onKey(e, indice)}
                  onFocus={() => setFoco(indice)}
                  onClick={() => setElegida({ tooth, surface })}
                  className={`m-px w-8 rounded border text-[10px] ${estado ? "bg-amber-200" : "bg-white"} focus:outline focus:outline-2`}
                >
                  {surface}
                  {estado ? <span aria-hidden="true">·{shortCode(estado.code)}</span> : null}
                </button>
              );
            })}
          </div>
        ))}
      </div>
      {elegida ? (
        <label className="mt-3 block text-sm">
          {`Estado para pieza ${elegida.tooth}, cara ${surfaceLabel(elegida.tooth, elegida.surface)}`}
          <select
            className="ml-2 rounded border px-2 py-1"
            value=""
            onChange={(e) => {
              onDraft(elegida.tooth, elegida.surface, e.target.value === "__clear" ? null : e.target.value);
              setElegida(null);
            }}
          >
            <option value="" disabled>
              Elegir…
            </option>
            {aplicables.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
            <option value="__clear">Limpiar</option>
          </select>
        </label>
      ) : null}
    </div>
  );
}
