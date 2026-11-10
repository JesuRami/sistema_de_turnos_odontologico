/**
 * Cambios pendientes de enviar (C-14, D11): recepción ve qué quedó en cola sin red, qué se envió y
 * qué falló, y puede reintentar ya. Sin datos de contacto (la etiqueta solo dice qué y cuándo).
 */
import { messageFor } from "../api/errors";
import { ApiError } from "../api/client";
import { retryQueue, useRetryQueue, type QueuedChange, type RetryQueue } from "./retryQueue";

const ESTADO: Record<QueuedChange["status"], string> = {
  pending: "En cola",
  sending: "Enviando…",
  done: "Enviado",
  failed: "No se pudo enviar"
};

export function RetryQueueIndicator({ queue = retryQueue }: { queue?: RetryQueue }): JSX.Element | null {
  const cambios = useRetryQueue(queue);
  if (cambios.length === 0) {
    return null;
  }
  const pendientes = cambios.filter((c) => c.status === "pending" || c.status === "sending").length;
  return (
    <section
      aria-label="Cambios pendientes de enviar"
      className="border-b border-sky-300 bg-sky-50 px-4 py-2 text-sm text-sky-950 print:hidden"
    >
      <div className="flex flex-wrap items-center gap-3">
        <strong>
          {pendientes > 0
            ? `${pendientes} ${pendientes === 1 ? "cambio pendiente" : "cambios pendientes"} de enviar. No cierres esta pestaña.`
            : "Cambios en cola procesados"}
        </strong>
        {pendientes > 0 && (
          <button
            type="button"
            className="rounded border border-sky-700/40 bg-white px-2 py-0.5 text-xs hover:bg-sky-100"
            onClick={() => void queue.flush(true)}
          >
            Reintentar ahora
          </button>
        )}
      </div>
      <ul className="mt-1 space-y-0.5">
        {cambios.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center gap-2">
            <span>{c.label}</span>
            <span className="text-xs opacity-80">· {ESTADO[c.status]}</span>
            {c.status === "failed" && c.error !== null && (
              <span className="text-xs text-rose-800">{messageFor(new ApiError(409, c.error))}</span>
            )}
            {(c.status === "done" || c.status === "failed") && (
              <button
                type="button"
                className="text-xs underline"
                aria-label={`Quitar aviso: ${c.label}`}
                onClick={() => queue.dismiss(c.id)}
              >
                Ocultar
              </button>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
