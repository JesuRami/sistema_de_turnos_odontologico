/**
 * Flujo público de reserva (D12): profesional → día → hora → datos → confirmación.
 * Mobile-first, una sola columna. Todo en memoria (sin storage). Las horas se muestran siempre
 * en la zona de la clínica.
 */
import { QueryClient, QueryClientProvider, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useClock } from "../../shared/time/now";
import { dateKeyOf, type DateKey } from "../../shared/time/zoned";
import { createBooking, fetchAvailability } from "./api";
import BookingError from "./BookingError";
import { describeProblem, type BookingProblem } from "./bookingErrors";
import Confirmation from "./Confirmation";
import ContactStep from "./ContactStep";
import DayStep from "./DayStep";
import ProfessionalStep, { CHOICE, CHOICE_OFF } from "./ProfessionalStep";
import { availabilityKey, useAvailability, useCatalog, windowRange, WINDOWS } from "./queries";
import TimeStep from "./TimeStep";
import type { BookingCatalog, BookingPatient, BookingSlot } from "./types";
import { useBookingFlow, type BookingStep } from "./useBookingFlow";
import WaitlistStep from "./WaitlistStep";

const TITULOS: Record<BookingStep, string> = {
  professional: "Elegí profesional",
  day: "Elegí el día",
  time: "Elegí el horario",
  contact: "Tus datos",
  done: "Turno reservado"
};

interface FlowProps {
  slug: string;
  catalog: BookingCatalog;
}

function Flow({ slug, catalog }: FlowProps): JSX.Element {
  const unico = catalog.professionals.length === 1 ? (catalog.professionals[0]?.id ?? null) : null;
  const [flow, dispatch] = useBookingFlow(unico);
  const clock = useClock();
  const queryClient = useQueryClient();
  const tz = catalog.timezone;
  const hoy = useMemo(() => dateKeyOf(clock(), tz), [clock, tz]);
  const range = windowRange(hoy, flow.windowIndex, tz);
  const disponibilidad = useAvailability(slug, flow.professionalId, range);
  const [problem, setProblem] = useState<BookingProblem | null>(null);
  // C-12: camino alternativo "anotarme en la lista de espera" desde los pasos de día y hora.
  const [enEspera, setEnEspera] = useState(false);
  const ultimoPaciente = useRef<BookingPatient | null>(null);
  const titulo = useRef<HTMLHeadingElement>(null);

  // Prefetch de la ventana siguiente cuando la actual ya cargó.
  const { professionalId, windowIndex } = flow;
  useEffect(() => {
    if (professionalId === null || !disponibilidad.isSuccess || windowIndex >= WINDOWS - 1) {
      return;
    }
    const siguiente = windowRange(hoy, windowIndex + 1, tz);
    void queryClient.prefetchQuery({
      queryKey: availabilityKey(slug, professionalId, siguiente.from),
      queryFn: () => fetchAvailability(slug, professionalId, siguiente),
      staleTime: 30_000
    });
  }, [disponibilidad.isSuccess, professionalId, windowIndex, hoy, tz, slug, queryClient]);

  // El foco sigue al paso (lectores de pantalla y teclado).
  useEffect(() => {
    titulo.current?.focus();
  }, [flow.step]);

  const slotsPorDia = useMemo(() => {
    const dias = new Map<DateKey, BookingSlot[]>();
    for (const slot of disponibilidad.data?.slots ?? []) {
      const dia = dateKeyOf(new Date(slot.starts_at), tz);
      dias.set(dia, [...(dias.get(dia) ?? []), slot]);
    }
    return dias;
  }, [disponibilidad.data, tz]);
  const dias = useMemo(() => [...slotsPorDia.keys()].sort(), [slotsPorDia]);

  const reservar = useMutation({
    mutationFn: ({ startsAt, patient }: { startsAt: string; patient: BookingPatient }) =>
      createBooking(slug, {
        professional_id: flow.professionalId ?? "",
        starts_at: startsAt,
        patient
      }),
    onSuccess: (result) => {
      setProblem(null);
      dispatch({ type: "done", result });
    },
    onError: (error) => setProblem(describeProblem(error))
  });

  function enviar(patient: BookingPatient, startsAt: string | null = flow.slot): void {
    if (startsAt === null) {
      return;
    }
    ultimoPaciente.current = patient;
    setProblem(null);
    reservar.mutate({ startsAt, patient });
  }

  function elegirAlternativo(slot: BookingSlot): void {
    if (ultimoPaciente.current !== null) {
      enviar(ultimoPaciente.current, slot.starts_at);
    }
  }

  const primerPaso: BookingStep = unico === null ? "professional" : "day";
  const pasos = unico === null ? 4 : 3;
  const indice = (["professional", "day", "time", "contact"] as const).indexOf(
    flow.step === "done" ? "contact" : flow.step
  );
  const numero = indice + 1 - (unico === null ? 0 : 1);
  const profesional = catalog.professionals.find((p) => p.id === flow.professionalId);

  if (enEspera) {
    return (
      <>
        <h2 className="mt-4 text-xl font-semibold">Lista de espera</h2>
        <WaitlistStep
          slug={slug}
          catalog={catalog}
          professionalId={flow.professionalId}
          today={hoy}
          onCancel={() => setEnEspera(false)}
        />
      </>
    );
  }

  return (
    <>
      {flow.step !== "done" && (
        <p className="mt-1 text-sm opacity-80">
          Paso {numero} de {pasos}
        </p>
      )}
      {flow.step !== "done" && flow.step !== primerPaso && (
        <button
          type="button"
          className={`${CHOICE} ${CHOICE_OFF} mt-3`}
          onClick={() => {
            setProblem(null);
            dispatch({ type: "back" });
          }}
        >
          Volver
        </button>
      )}
      <h2 ref={titulo} tabIndex={-1} className="mt-4 text-xl font-semibold focus:outline-none">
        {TITULOS[flow.step]}
      </h2>
      {flow.step === "professional" && (
        <ProfessionalStep
          professionals={catalog.professionals}
          selectedId={flow.professionalId}
          onSelect={(id) => dispatch({ type: "professional", id })}
        />
      )}
      {flow.step === "day" && (
        <DayStep
          days={dias}
          selected={flow.day}
          loading={disponibilidad.isPending}
          error={disponibilidad.error}
          windowIndex={flow.windowIndex}
          onSelect={(day) => dispatch({ type: "day", day })}
          onWindow={(index) => dispatch({ type: "window", index })}
        />
      )}
      {flow.step === "time" && flow.day !== null && (
        <TimeStep
          slots={slotsPorDia.get(flow.day) ?? []}
          timezone={tz}
          selected={flow.slot}
          onSelect={(startsAt) => dispatch({ type: "slot", startsAt })}
        />
      )}
      {(flow.step === "day" || flow.step === "time") && (
        <div className="mt-6 rounded-lg border border-dental-600/20 bg-white p-3 text-sm">
          <p>¿Ningún horario te sirve?</p>
          <button
            type="button"
            className={`${CHOICE} ${CHOICE_OFF} mt-2 w-full`}
            onClick={() => setEnEspera(true)}
          >
            Anotarme en la lista de espera
          </button>
        </div>
      )}
      {flow.step === "contact" && (
        <ContactStep
          timezone={tz}
          pending={reservar.isPending}
          problem={problem}
          onSubmit={(patient) => enviar(patient)}
          onPickAlternative={elegirAlternativo}
          onChooseAnother={() => {
            setProblem(null);
            dispatch({ type: "back" });
          }}
        />
      )}
      {flow.step === "done" && flow.result !== null && (
        <Confirmation
          result={flow.result}
          professionalName={profesional?.display_name ?? ""}
          timezone={tz}
        />
      )}
    </>
  );
}

function BookingContent(): JSX.Element {
  const { slug = "" } = useParams<{ slug: string }>();
  const catalog = useCatalog(slug);

  return (
    <main className="mx-auto min-h-screen max-w-md bg-enamel px-4 pb-16 pt-8 text-dental-900">
      <h1 className="text-2xl font-semibold">
        {catalog.data?.name ?? "Reservar turno"}
      </h1>
      {catalog.isPending && <p className="mt-4 text-sm">Cargando…</p>}
      {catalog.isError && (
        <BookingError problem={describeProblem(catalog.error)} timezone="UTC" />
      )}
      {catalog.isSuccess && catalog.data.professionals.length === 0 && (
        <p className="mt-4 text-sm">
          Esta clínica no tiene profesionales disponibles para reservar online por ahora.
        </p>
      )}
      {catalog.isSuccess && catalog.data.professionals.length > 0 && (
        <Flow key={slug} slug={slug} catalog={catalog.data} />
      )}
    </main>
  );
}

/**
 * La reserva pública usa su PROPIO `QueryClient`: es anónima y no comparte caché con la sesión
 * del personal. Además el `AuthProvider` hace `queryClient.clear()` cuando el visitante resulta
 * anónimo, lo que dejaba el catálogo en vuelo colgado en "Cargando…" (hallado en el E2E).
 */
function BookingFlow(): JSX.Element {
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
      <BookingContent />
    </QueryClientProvider>
  );
}

export default BookingFlow;
