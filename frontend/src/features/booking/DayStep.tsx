import { formatDayLabel, type DateKey } from "../../shared/time/zoned";
import { describeProblem } from "./bookingErrors";
import { CHOICE, CHOICE_OFF, CHOICE_ON } from "./ProfessionalStep";
import { WINDOWS } from "./queries";

interface DayStepProps {
  days: readonly DateKey[];
  selected: DateKey | null;
  loading: boolean;
  error: unknown;
  windowIndex: number;
  onSelect: (day: DateKey) => void;
  onWindow: (index: number) => void;
}

function DayStep({
  days,
  selected,
  loading,
  error,
  windowIndex,
  onSelect,
  onWindow
}: DayStepProps): JSX.Element {
  return (
    <div className="mt-4">
      {error !== null && error !== undefined && (
        <p role="alert" className="rounded border border-rose-700/40 bg-rose-50 p-3 text-sm">
          {describeProblem(error).message}
        </p>
      )}
      {loading && <p className="text-sm">Buscando horarios…</p>}
      {!loading && !error && days.length === 0 && (
        <p className="text-sm">No hay horarios libres en estos días</p>
      )}
      <ul className="grid grid-cols-2 gap-2">
        {days.map((day) => (
          <li key={day}>
            <button
              type="button"
              aria-pressed={day === selected}
              className={`${CHOICE} w-full ${day === selected ? CHOICE_ON : CHOICE_OFF}`}
              onClick={() => onSelect(day)}
            >
              {formatDayLabel(day)}
            </button>
          </li>
        ))}
      </ul>
      <div className="mt-4 flex justify-between gap-2">
        <button
          type="button"
          className={`${CHOICE} ${CHOICE_OFF} disabled:opacity-40`}
          disabled={windowIndex === 0}
          onClick={() => onWindow(windowIndex - 1)}
        >
          Ver días anteriores
        </button>
        <button
          type="button"
          className={`${CHOICE} ${CHOICE_OFF} disabled:opacity-40`}
          disabled={windowIndex >= WINDOWS - 1}
          onClick={() => onWindow(windowIndex + 1)}
        >
          Ver más días
        </button>
      </div>
    </div>
  );
}

export default DayStep;
