/**
 * Cancelación con motivo opcional de la lista cerrada del servidor (D7). La nota libre solo
 * aparece con «Otro» y se limita a 200 caracteres. La acción destructiva se confirma acá.
 */
import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { whenLabel } from "./format";
import { DANGER, SECONDARY } from "./ManageContact";
import type { ManageActionRequest, ManageView, PatientReason } from "./types";

const NOTE_MAX = 200;

interface CancelDialogProps {
  view: ManageView;
  pending: boolean;
  onSubmit: (action: ManageActionRequest) => void;
  onClose: () => void;
}

function CancelDialog({ view, pending, onSubmit, onClose }: CancelDialogProps): JSX.Element {
  const [reason, setReason] = useState<PatientReason | null>(null);
  const [note, setNote] = useState("");
  const titulo = useRef<HTMLHeadingElement>(null);
  const tituloId = useId();
  const notaId = useId();

  useEffect(() => {
    titulo.current?.focus();
    function alEscape(evento: KeyboardEvent): void {
      if (evento.key === "Escape") {
        onClose();
      }
    }
    document.addEventListener("keydown", alEscape);
    return () => document.removeEventListener("keydown", alEscape);
  }, [onClose]);

  function enviar(evento: FormEvent): void {
    evento.preventDefault();
    const accion: ManageActionRequest = { action: "cancel" };
    if (reason !== null) {
      accion.reason = reason;
    }
    const nota = note.trim();
    if (reason === "otro" && nota !== "") {
      accion.note = nota;
    }
    onSubmit(accion);
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={tituloId}
      className="mt-4 rounded-lg border-2 border-rose-700/40 bg-white p-4"
    >
      <h2 id={tituloId} ref={titulo} tabIndex={-1} className="text-lg font-semibold focus:outline-none">
        Cancelar turno
      </h2>
      <p className="mt-1 text-sm opacity-80">
        {whenLabel(view.appointment.starts_at, view.clinic.timezone)} ·{" "}
        {view.appointment.professional_display_name}
      </p>
      <form className="mt-4" onSubmit={enviar}>
        <fieldset>
          <legend className="text-sm font-medium">
            ¿Por qué no podés asistir? <span className="opacity-70">(opcional)</span>
          </legend>
          <div className="mt-2 flex flex-col gap-2">
            {view.reason_options.map((opcion) => (
              <label
                key={opcion.value}
                className="flex min-h-11 items-center gap-3 rounded-lg border border-dental-600/30 px-3 text-sm"
              >
                <input
                  type="radio"
                  name="motivo"
                  value={opcion.value}
                  checked={reason === opcion.value}
                  onChange={() => setReason(opcion.value)}
                />
                {opcion.label}
              </label>
            ))}
          </div>
        </fieldset>
        {reason === "otro" && (
          <div className="mt-3 text-sm">
            <label htmlFor={notaId} className="font-medium">
              Contanos brevemente <span className="opacity-70">(opcional, máx. 200 caracteres)</span>
            </label>
            <textarea
              id={notaId}
              rows={3}
              maxLength={NOTE_MAX}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              className="mt-1 block w-full rounded border border-dental-600/30 bg-white px-2 py-1.5 focus:border-dental-600 focus:outline-none focus:ring-1 focus:ring-dental-600"
            />
            <span className="mt-0.5 block text-xs opacity-70">
              La lee solo el equipo de la clínica.
            </span>
          </div>
        )}
        <p className="mt-4 rounded border border-amber-700/40 bg-amber-50 p-3 text-sm">
          Si cancelás, el horario queda libre para otra persona y no se puede deshacer.
        </p>
        <div className="mt-4 flex flex-col gap-2">
          <button type="submit" className={DANGER} disabled={pending}>
            Confirmar cancelación
          </button>
          <button type="button" className={SECONDARY} onClick={onClose}>
            Volver sin cancelar
          </button>
        </div>
      </form>
    </div>
  );
}

export default CancelDialog;
