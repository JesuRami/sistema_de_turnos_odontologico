/**
 * Página pública `/g/:token` (C-08, D14): mobile-first, una columna. El token se lee solo de
 * la URL y nunca se guarda (ni storage, ni cookies, ni otra ruta). Las reglas las decide el
 * servidor (`actions`, `blocked_reason`); la página solo las muestra.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import CancelDialog from "./CancelDialog";
import { whenLabel } from "./format";
import { LinkUnavailable, ManageError } from "./ManageError";
import { describeManageProblem } from "./manageErrors";
import ManageSummary from "./ManageSummary";
import { useManageView } from "./queries";
import ReschedulePanel from "./ReschedulePanel";
import type { ManageActionRequest, ManageView } from "./types";
import { useManageActions } from "./useManageActions";

type Mode = "summary" | "cancel" | "reschedule";

/** Metas de la página mientras está montada: sin `Referer` y fuera de buscadores (D2). */
function usePrivatePageMeta(): void {
  useEffect(() => {
    const metas = [
      ["referrer", "no-referrer"],
      ["robots", "noindex"]
    ].map(([name, content]) => {
      const meta = document.createElement("meta");
      meta.name = name ?? "";
      meta.content = content ?? "";
      document.head.appendChild(meta);
      return meta;
    });
    return () => metas.forEach((meta) => meta.remove());
  }, []);
}

function notice(action: ManageActionRequest["action"], view: ManageView): string {
  if (action === "confirm") {
    return "Tu turno quedó confirmado.";
  }
  if (action === "cancel") {
    return "Cancelaste tu turno.";
  }
  return `Tu turno quedó para ${whenLabel(view.appointment.starts_at, view.clinic.timezone)}.`;
}

function Manage({ token, view: cacheada }: { token: string; view: ManageView }): JSX.Element {
  const [mode, setMode] = useState<Mode>("summary");
  const acciones = useManageActions(token, cacheada.policy.cancellation_window_hours);
  // La respuesta de la acción se muestra en el MISMO render en que termina la mutación: la
  // caché se actualiza en otro commit y, entre ambos, un segundo toque caería sobre el botón
  // viejo (doble envío).
  const view = acciones.done?.view ?? cacheada;

  function run(action: ManageActionRequest): void {
    acciones.run(action);
  }

  // Al terminar una acción se vuelve al resumen; un 409 de horario deja abierto el panel.
  useEffect(() => {
    if (acciones.done !== null) {
      setMode("summary");
    } else if (acciones.problem !== null && acciones.problem.alternatives.length === 0) {
      setMode("summary");
    }
  }, [acciones.done, acciones.problem]);

  if (acciones.problem?.linkGone === true) {
    return <LinkUnavailable clinic={acciones.problem.expiredClinic} />;
  }
  return (
    <>
      {acciones.done !== null && (
        <p role="status" className="mt-4 rounded-lg border border-emerald-700/40 bg-emerald-50 p-3 text-sm">
          {notice(acciones.done.action, acciones.done.view)}
        </p>
      )}
      {acciones.problem !== null && (
        <ManageError
          problem={acciones.problem}
          clinicName={view.clinic.name}
          phone={view.clinic.phone}
          timezone={view.clinic.timezone}
          disabled={acciones.pending}
          onPickAlternative={(slot) => run({ action: "reschedule", starts_at: slot.starts_at })}
        />
      )}
      {mode === "summary" && (
        <ManageSummary
          view={view}
          busy={acciones.pending}
          onConfirm={() => run({ action: "confirm" })}
          onCancel={() => {
            acciones.clear();
            setMode("cancel");
          }}
          onReschedule={() => {
            acciones.clear();
            setMode("reschedule");
          }}
        />
      )}
      {mode === "cancel" && (
        <CancelDialog
          view={view}
          pending={acciones.pending}
          onSubmit={run}
          onClose={() => setMode("summary")}
        />
      )}
      {mode === "reschedule" && (
        <ReschedulePanel
          token={token}
          view={view}
          pending={acciones.pending}
          onSubmit={(startsAt) => run({ action: "reschedule", starts_at: startsAt })}
          onClose={() => setMode("summary")}
        />
      )}
    </>
  );
}

function ManageContent({ token }: { token: string }): JSX.Element {
  const vista = useManageView(token);
  const problema = vista.isError ? describeManageProblem(vista.error, 0) : null;

  return (
    <main className="mx-auto min-h-screen max-w-md bg-enamel px-4 pb-16 pt-8 text-dental-900">
      <p className="text-xs uppercase tracking-wide opacity-70">Tu turno</p>
      <h1 className="text-2xl font-semibold">{vista.data?.clinic.name ?? "Gestionar mi turno"}</h1>
      <div aria-live="polite">
        {vista.isPending && <p className="mt-4 text-sm">Cargando tu turno…</p>}
      </div>
      {problema !== null && problema.linkGone && <LinkUnavailable clinic={problema.expiredClinic} />}
      {problema !== null && !problema.linkGone && (
        <p role="alert" className="mt-4 rounded-lg border border-rose-700/40 bg-rose-50 p-4 text-sm">
          {problema.message}
        </p>
      )}
      {vista.isSuccess && <Manage token={token} view={vista.data} />}
    </main>
  );
}

/**
 * QueryClient PROPIO, como la reserva pública: la ruta es anónima y el `AuthProvider` limpia
 * la caché compartida cuando el visitante resulta anónimo (dejaría la vista colgada).
 */
function ManageFlow(): JSX.Element {
  const { token = "" } = useParams<{ token: string }>();
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false },
          mutations: { retry: false }
        }
      })
  );
  usePrivatePageMeta();
  return (
    <QueryClientProvider client={client}>
      <ManageContent key={token} token={token} />
    </QueryClientProvider>
  );
}

export default ManageFlow;
