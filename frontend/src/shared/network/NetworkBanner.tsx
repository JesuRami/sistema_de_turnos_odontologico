/**
 * Aviso de conexión (C-14, D11; SU-06). Aparece cuando el navegador está offline o el último
 * pedido no llegó al servidor; desaparece con la primera respuesta. Lo que ya está en pantalla
 * sigue visible (TanStack conserva los datos ante un error de refetch).
 */
import { isDisconnected, useNetworkStatus } from "./status";

function hora(ms: number): string {
  return new Intl.DateTimeFormat("es-AR", { hour: "2-digit", minute: "2-digit" }).format(new Date(ms));
}

export function NetworkBanner({ offlineHint }: { offlineHint?: string }): JSX.Element | null {
  const estado = useNetworkStatus();
  if (!isDisconnected(estado)) {
    return null;
  }
  const ultimo = estado.lastOkAt !== null ? ` Último dato recibido: ${hora(estado.lastOkAt)}.` : "";
  return (
    <div
      role="status"
      aria-live="polite"
      className="border-b border-amber-300 bg-amber-50 px-4 py-2 text-sm text-amber-950 print:hidden"
    >
      <strong>Sin conexión con el servidor.</strong> Lo que ves puede estar desactualizado.{ultimo}
      {offlineHint !== undefined ? ` ${offlineHint}` : ""}
    </div>
  );
}
