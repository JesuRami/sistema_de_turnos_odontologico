import { useState } from "react";
import { dateKeyOf, formatDayLabel, formatTime } from "../../shared/time/zoned";
import { CHOICE, CHOICE_ON } from "./ProfessionalStep";
import type { BookingResult, BookingWarning } from "./types";

const AVISOS: Record<BookingWarning, string> = {
  phone_invalid_email_channel:
    "No pudimos usar tu teléfono, así que te avisamos por email. Podés corregirlo en la clínica.",
  whatsapp_declined_email_channel: "Elegiste no recibir WhatsApp: te avisamos por email."
};

interface ConfirmationProps {
  result: BookingResult;
  professionalName: string;
  timezone: string;
}

/** El elemento memorable de la reserva: el link de gestión, visible una sola vez, copiable. */
function Confirmation({ result, professionalName, timezone }: ConfirmationProps): JSX.Element {
  const [copied, setCopied] = useState(false);
  const inicio = new Date(result.starts_at);

  async function copiar(): Promise<void> {
    try {
      await navigator.clipboard.writeText(result.manage_url);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="mt-4">
      <p className="text-lg">
        {formatDayLabel(dateKeyOf(inicio, timezone))} · {formatTime(inicio, timezone)} con{" "}
        {professionalName}
      </p>
      <p className="mt-1 text-sm">
        Canal de avisos: {result.channel === "whatsapp" ? "WhatsApp" : "email"}
      </p>
      <p className="mt-1 text-sm">La clínica va a confirmar tu turno.</p>
      {result.warnings.map((aviso) => (
        <p key={aviso} className="mt-3 rounded border border-amber-700/40 bg-amber-50 p-3 text-sm">
          {AVISOS[aviso]}
        </p>
      ))}
      <div className="mt-6 rounded-lg border-2 border-dental-600 bg-white p-4">
        <label htmlFor="manage-link" className="text-sm font-medium">
          Link para gestionar tu turno
        </label>
        <input
          id="manage-link"
          readOnly
          value={result.manage_url}
          onFocus={(e) => e.currentTarget.select()}
          className="mt-2 block min-h-11 w-full rounded border border-dental-600/30 bg-dental-50 px-3 text-sm"
        />
        <p className="mt-2 text-xs">
          Guardalo ahora: es la única vez que lo mostramos. Con ese link vas a poder consultar o
          cambiar tu turno.
        </p>
        <button type="button" className={`${CHOICE} ${CHOICE_ON} mt-3 w-full`} onClick={copiar}>
          Copiar link
        </button>
        <p role="status" className="mt-2 min-h-5 text-sm">
          {copied ? "Link copiado" : ""}
        </p>
      </div>
    </div>
  );
}

export default Confirmation;
