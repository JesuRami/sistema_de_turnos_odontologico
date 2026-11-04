import { dateKeyOf, formatDayLabel, formatTime } from "../../shared/time/zoned";
import type { BookingProblem } from "./bookingErrors";
import { CHOICE, CHOICE_OFF } from "./ProfessionalStep";
import type { BookingSlot } from "./types";

interface BookingErrorProps {
  problem: BookingProblem;
  timezone: string;
  disabled?: boolean;
  /** Reenvía la reserva con los mismos datos en otro horario (409). */
  onPickAlternative?: (slot: BookingSlot) => void;
  /** Vuelve a elegir horario cuando no hay alternativas. */
  onChooseAnother?: () => void;
}

function BookingError({
  problem,
  timezone,
  disabled = false,
  onPickAlternative,
  onChooseAnother
}: BookingErrorProps): JSX.Element {
  return (
    <div role="alert" className="mt-4 rounded-lg border border-rose-700/40 bg-rose-50 p-4 text-sm">
      <p className="font-medium">{problem.message}</p>
      {problem.alternatives.length > 0 && onPickAlternative !== undefined && (
        <>
          <p className="mt-2">Estos horarios siguen libres:</p>
          <ul className="mt-2 flex flex-col gap-2">
            {problem.alternatives.map((slot) => {
              const inicio = new Date(slot.starts_at);
              const etiqueta = `${formatDayLabel(dateKeyOf(inicio, timezone))} ${formatTime(inicio, timezone)}`;
              return (
                <li key={slot.starts_at}>
                  <button
                    type="button"
                    disabled={disabled}
                    className={`${CHOICE} ${CHOICE_OFF} w-full text-left disabled:opacity-50`}
                    onClick={() => onPickAlternative(slot)}
                  >
                    Reservar {etiqueta}
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}
      {problem.slotLost && problem.alternatives.length === 0 && onChooseAnother !== undefined && (
        <button
          type="button"
          className={`${CHOICE} ${CHOICE_OFF} mt-3`}
          onClick={onChooseAnother}
        >
          Elegir otro horario
        </button>
      )}
    </div>
  );
}

export default BookingError;
