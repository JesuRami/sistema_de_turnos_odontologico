import { formatTime } from "../../shared/time/zoned";
import { CHOICE, CHOICE_OFF, CHOICE_ON } from "./ProfessionalStep";
import type { BookingSlot } from "./types";

interface TimeStepProps {
  slots: readonly BookingSlot[];
  timezone: string;
  selected: string | null;
  onSelect: (startsAt: string) => void;
}

function TimeStep({ slots, timezone, selected, onSelect }: TimeStepProps): JSX.Element {
  return (
    <ul className="mt-4 grid grid-cols-3 gap-2 sm:grid-cols-4">
      {slots.map((slot) => (
        <li key={slot.starts_at}>
          <button
            type="button"
            aria-pressed={slot.starts_at === selected}
            className={`${CHOICE} w-full px-2 text-center tabular-nums ${
              slot.starts_at === selected ? CHOICE_ON : CHOICE_OFF
            }`}
            onClick={() => onSelect(slot.starts_at)}
          >
            {formatTime(new Date(slot.starts_at), timezone)}
          </button>
        </li>
      ))}
    </ul>
  );
}

export default TimeStep;
