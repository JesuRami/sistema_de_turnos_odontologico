/**
 * Página pública `/o/:token` de una oferta de la lista de espera (C-12; spec web/waitlist-offer).
 * Mobile-first, una columna. El token solo vive en la URL: nada se guarda en el navegador. Usa su
 * PROPIO `QueryClient`, como `/b/:slug` y `/g/:token` (el `AuthProvider` limpia la caché del
 * visitante anónimo).
 */
import {
  QueryClient,
  QueryClientProvider,
  useMutation,
  useQuery,
  useQueryClient
} from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { ApiError } from "../../shared/api/client";
import { publicFetch } from "../../shared/api/public";
import { dateKeyOf, formatDayLabel, formatTime } from "../../shared/time/zoned";
import { CHOICE, CHOICE_OFF, CHOICE_ON } from "../booking/ProfessionalStep";

type OfferStatus = "pending" | "accepted" | "declined" | "expired" | "cancelled";

export interface OfferView {
  clinic_name: string;
  clinic_phone: string | null;
  timezone: string;
  booking_url: string | null;
  patient_first_name: string;
  professional_name: string;
  starts_at: string;
  ends_at: string;
  expires_at: string;
  status: OfferStatus;
  appointment: { starts_at: string; ends_at: string; manage_url: string } | null;
}

interface Alternative {
  starts_at: string;
  ends_at: string;
}

type Accion = { tipo: "accept" } | { tipo: "decline"; leaveList: boolean };

const base = (token: string): string => `/api/waitlist-offer/${encodeURIComponent(token)}`;

function cuando(iso: string, tz: string): string {
  const instante = new Date(iso);
  return `${formatDayLabel(dateKeyOf(instante, tz))} a las ${formatTime(instante, tz)}`;
}

function isAlternative(value: unknown): value is Alternative {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Alternative).starts_at === "string" &&
    typeof (value as Alternative).ends_at === "string"
  );
}

function Contacto({ view }: { view: Pick<OfferView, "clinic_name" | "clinic_phone"> }): JSX.Element {
  return (
    <p className="mt-3 text-sm">
      Si necesitás ayuda, comunicate con {view.clinic_name}
      {view.clinic_phone !== null ? ` al ${view.clinic_phone}` : ""}.
    </p>
  );
}

function Problema({ error, view }: { error: unknown; view: OfferView }): JSX.Element {
  const tz = view.timezone;
  if (error instanceof ApiError && error.detail === "slot_taken") {
    const alternativos = Array.isArray(error.extra.alternatives)
      ? error.extra.alternatives.filter(isAlternative)
      : [];
    return (
      <div role="alert" className="mt-4 rounded-lg border border-amber-700/40 bg-amber-50 p-3 text-sm">
        <p>
          Ese turno ya lo tomó otra persona. Seguís en la lista de espera con prioridad y te avisamos
          del próximo.
        </p>
        {alternativos.length > 0 && (
          <>
            <p className="mt-2">Hay horarios libres con {view.professional_name}:</p>
            <ul className="mt-1 list-disc pl-5">
              {alternativos.map((a) => (
                <li key={a.starts_at}>{cuando(a.starts_at, tz)}</li>
              ))}
            </ul>
          </>
        )}
        {view.booking_url !== null && (
          <a className="mt-2 inline-block underline" href={view.booking_url}>
            Reservar otro horario online
          </a>
        )}
      </div>
    );
  }
  const textos: Record<string, string> = {
    offer_expired: "La oferta ya venció.",
    offer_closed: "La oferta ya fue respondida o cerrada.",
    patient_busy: "Ya tenés otro turno a esa hora, así que no pudimos tomar este.",
    rate_limited: "Hiciste muchos intentos seguidos. Esperá un momento y probá de nuevo.",
    network_error: "No hay conexión. Revisá tu internet y probá de nuevo."
  };
  const detalle = error instanceof ApiError ? error.detail : "network_error";
  return (
    <div role="alert" className="mt-4 rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm">
      {textos[detalle] ?? "No pudimos registrar tu respuesta. Probá de nuevo en unos minutos."}
      <Contacto view={view} />
    </div>
  );
}

function Oferta({ token, view }: { token: string; view: OfferView }): JSX.Element {
  const queryClient = useQueryClient();
  const enviando = useRef(false);
  const [resultado, setResultado] = useState<OfferView | null>(null);
  const accion = useMutation({
    mutationFn: (a: Accion) =>
      a.tipo === "accept"
        ? publicFetch<OfferView>(`${base(token)}/accept`, { method: "POST" })
        : publicFetch<OfferView>(`${base(token)}/decline`, {
            method: "POST",
            body: { leave_list: a.leaveList }
          }),
    onSuccess: (nueva) => {
      setResultado(nueva);
      queryClient.setQueryData(["waitlist-offer", token], nueva);
    },
    onSettled: () => {
      enviando.current = false;
    }
  });

  function responder(a: Accion): void {
    if (enviando.current) {
      return; // doble toque: una sola request
    }
    enviando.current = true;
    accion.mutate(a);
  }

  const actual = resultado ?? view;
  const tz = actual.timezone;
  const abierta = actual.status === "pending";

  return (
    <>
      <p className="mt-2 text-sm">Hola {actual.patient_first_name},</p>
      <div className="mt-3 rounded-lg border-2 border-dental-600 bg-white p-4">
        <p className="text-lg font-semibold">{cuando(actual.starts_at, tz)}</p>
        <p className="text-sm">con {actual.professional_name}</p>
        {abierta && (
          <p className="mt-2 text-sm font-medium">
            Tenés hasta las {formatTime(new Date(actual.expires_at), tz)} para tomarlo.
          </p>
        )}
      </div>

      {actual.status === "accepted" && actual.appointment !== null && (
        <div role="status" className="mt-4 rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm">
          <p className="font-semibold">Turno confirmado</p>
          <p>{cuando(actual.appointment.starts_at, tz)}</p>
          <a className="mt-2 inline-block underline" href={actual.appointment.manage_url}>
            Ver o cambiar mi turno
          </a>
        </div>
      )}
      {actual.status === "declined" && (
        <p role="status" className="mt-4 text-sm">
          Listo, dejamos pasar este turno.
          {resultado !== null && accion.variables?.tipo === "decline" && accion.variables.leaveList
            ? " Saliste de la lista de espera."
            : " Seguís en la lista de espera."}
        </p>
      )}
      {(actual.status === "expired" || actual.status === "cancelled") && (
        <div className="mt-4 text-sm">
          <p>Esta oferta ya no está disponible{actual.status === "expired" ? ": venció" : ""}.</p>
          <Contacto view={actual} />
        </div>
      )}

      {accion.isError && <Problema error={accion.error} view={actual} />}

      {abierta && (
        <div className="mt-6 space-y-3">
          <button
            type="button"
            className={`${CHOICE} ${CHOICE_ON} w-full`}
            disabled={accion.isPending}
            onClick={() => responder({ tipo: "accept" })}
          >
            Tomar el turno
          </button>
          <button
            type="button"
            className={`${CHOICE} ${CHOICE_OFF} w-full`}
            disabled={accion.isPending}
            onClick={() => responder({ tipo: "decline", leaveList: false })}
          >
            No me sirve
          </button>
          <button
            type="button"
            className={`${CHOICE} ${CHOICE_OFF} w-full`}
            disabled={accion.isPending}
            onClick={() => responder({ tipo: "decline", leaveList: true })}
          >
            No me sirve y salir de la lista
          </button>
        </div>
      )}
    </>
  );
}

/** Metas de la página mientras está montada: sin `Referer` y fuera de buscadores. */
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

function OfferContent(): JSX.Element {
  usePrivatePageMeta();
  const { token = "" } = useParams<{ token: string }>();
  const vista = useQuery({
    queryKey: ["waitlist-offer", token],
    queryFn: () => publicFetch<OfferView>(base(token))
  });
  return (
    <main className="mx-auto min-h-screen max-w-md bg-enamel px-4 pb-16 pt-8 text-dental-900">
      <h1 className="text-2xl font-semibold">{vista.data?.clinic_name ?? "Turno disponible"}</h1>
      <p className="text-sm opacity-80">Se liberó un turno de la lista de espera</p>
      {vista.isPending && <p className="mt-4 text-sm">Cargando…</p>}
      {vista.isError && (
        <div role="alert" className="mt-4 rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm">
          {vista.error instanceof ApiError && vista.error.detail === "offer_not_found"
            ? "El link no es válido o ya venció. Si querías un turno, comunicate con la clínica."
            : vista.error instanceof ApiError && vista.error.detail === "rate_limited"
              ? "Hiciste muchos intentos seguidos. Esperá un momento y probá de nuevo."
              : "No pudimos cargar la oferta. Revisá tu conexión y probá de nuevo."}
        </div>
      )}
      {vista.isSuccess && <Oferta token={token} view={vista.data} />}
    </main>
  );
}

function OfferPage(): JSX.Element {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: false, staleTime: 0, refetchOnWindowFocus: false },
          mutations: { retry: false }
        }
      })
  );
  return (
    <QueryClientProvider client={client}>
      <OfferContent />
    </QueryClientProvider>
  );
}

export default OfferPage;
