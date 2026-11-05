/** Derivación a la clínica: teléfono si existe; si no, solo el nombre (degradación explícita). */

/** Botón grande (≥ 44 px) de la gestión; mismas proporciones que la reserva pública. */
export const ACTION =
  "inline-flex min-h-11 items-center justify-center rounded-lg px-4 py-2 text-base font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-dental-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed motion-reduce:transition-none";
export const PRIMARY = `${ACTION} bg-dental-600 text-white hover:bg-dental-700 disabled:bg-dental-600/50`;
export const SECONDARY = `${ACTION} border border-dental-600/40 bg-white text-dental-900 hover:bg-dental-50 disabled:opacity-50`;
export const DANGER = `${ACTION} bg-rose-700 text-white hover:bg-rose-800 disabled:bg-rose-700/50`;
export const GHOST_DANGER = `${ACTION} border border-rose-700/40 bg-white text-rose-800 hover:bg-rose-50 disabled:opacity-50`;

interface ManageContactProps {
  clinicName: string;
  phone: string | null;
}

function ManageContact({ clinicName, phone }: ManageContactProps): JSX.Element {
  if (phone === null) {
    return <p className="mt-3 text-sm">Comunicate con {clinicName}.</p>;
  }
  return (
    <div className="mt-3">
      <p className="text-xs opacity-80">Teléfono de {clinicName}</p>
      <p className="text-lg font-semibold">{phone}</p>
      <a className={`${PRIMARY} mt-3 w-full`} href={`tel:${phone}`}>
        Llamar a la clínica
      </a>
    </div>
  );
}

export default ManageContact;
