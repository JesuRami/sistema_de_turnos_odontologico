import type { BookingProfessional } from "./types";

/** Botón grande (≥ 44 px de alto) de las listas de opciones de la reserva. */
export const CHOICE =
  "min-h-11 rounded-lg border px-4 py-2 text-base font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-dental-600 focus-visible:ring-offset-2 motion-reduce:transition-none";
export const CHOICE_OFF = "border-dental-600/30 bg-white text-dental-900 hover:bg-dental-50";
export const CHOICE_ON = "border-dental-700 bg-dental-700 text-white";

interface ProfessionalStepProps {
  professionals: readonly BookingProfessional[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function ProfessionalStep({
  professionals,
  selectedId,
  onSelect
}: ProfessionalStepProps): JSX.Element {
  return (
    <ul className="mt-4 flex flex-col gap-2">
      {professionals.map((p) => (
        <li key={p.id}>
          <button
            type="button"
            aria-pressed={p.id === selectedId}
            className={`${CHOICE} w-full text-left ${p.id === selectedId ? CHOICE_ON : CHOICE_OFF}`}
            onClick={() => onSelect(p.id)}
          >
            {p.display_name}
          </button>
        </li>
      ))}
    </ul>
  );
}

export default ProfessionalStep;
