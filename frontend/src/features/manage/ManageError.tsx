/** Errores de la gestión: alerta de una acción fallida y pantalla de link no disponible. */
import { whenLabel } from "./format";
import ManageContact, { SECONDARY } from "./ManageContact";
import type { ManageProblem } from "./manageErrors";
import type { ExpiredClinic, ManageSlot } from "./types";

interface ManageErrorProps {
  problem: ManageProblem;
  clinicName: string;
  phone: string | null;
  timezone: string;
  disabled: boolean;
  /** Reenvía la reprogramación con el horario alternativo elegido (409 slot_taken). */
  onPickAlternative: (slot: ManageSlot) => void;
}

export function ManageError({
  problem,
  clinicName,
  phone,
  timezone,
  disabled,
  onPickAlternative
}: ManageErrorProps): JSX.Element {
  return (
    <div role="alert" className="mt-4 rounded-lg border border-rose-700/40 bg-rose-50 p-4 text-sm">
      <p className="font-medium">{problem.message}</p>
      {problem.alternatives.length > 0 && (
        <>
          <p className="mt-2">Estos horarios siguen libres:</p>
          <ul className="mt-2 flex flex-col gap-2">
            {problem.alternatives.map((slot) => (
              <li key={slot.starts_at}>
                <button
                  type="button"
                  disabled={disabled}
                  className={`${SECONDARY} w-full`}
                  onClick={() => onPickAlternative(slot)}
                >
                  Pasar a {whenLabel(slot.starts_at, timezone)}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {problem.contact && <ManageContact clinicName={clinicName} phone={phone} />}
    </div>
  );
}

/** Pantalla de contacto para `404`/`410` (RN-ON-04): nada del turno, ninguna acción. */
export function LinkUnavailable({ clinic }: { clinic: ExpiredClinic | null }): JSX.Element {
  return (
    <section className="mt-4">
      <h2 className="text-xl font-semibold">Este link ya no está disponible</h2>
      <p role="status" className="mt-3 rounded-lg border border-dental-600/20 bg-white p-4 text-sm">
        Por seguridad, el link para gestionar un turno vence un tiempo después del turno. Si
        todavía necesitás confirmar, cancelar o cambiar tu turno, comunicate con la clínica.
      </p>
      {clinic !== null && (
        <div className="mt-4 rounded-lg border border-dental-600/20 bg-white p-4">
          <p className="font-medium">{clinic.name}</p>
          <ManageContact clinicName={clinic.name} phone={clinic.phone} />
        </div>
      )}
    </section>
  );
}
