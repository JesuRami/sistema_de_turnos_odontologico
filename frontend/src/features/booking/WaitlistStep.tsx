/**
 * Anotarse en la lista de espera desde la reserva pública (C-12; spec web/public-booking).
 * Camino alternativo cuando ningún horario sirve: profesional o "Cualquiera", período, franja y
 * días opcionales y los mismos datos y consentimientos que la reserva. Nada se guarda en el
 * navegador.
 */
import { useMutation } from "@tanstack/react-query";
import { useId, useState } from "react";
import { ApiError } from "../../shared/api/client";
import { joinWaitlist } from "./api";
import ContactStep from "./ContactStep";
import { CHOICE, CHOICE_OFF } from "./ProfessionalStep";
import type { BookingCatalog, BookingPatient, WaitlistJoined } from "./types";

const DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"] as const;
const INPUT =
  "mt-1 block min-h-11 w-full rounded-lg border border-dental-600/30 bg-white px-3 text-base focus:border-dental-600 focus:outline-none focus:ring-2 focus:ring-dental-600";

function sumarDias(iso: string, dias: number): string {
  const fecha = new Date(`${iso}T12:00:00Z`);
  fecha.setUTCDate(fecha.getUTCDate() + dias);
  return fecha.toISOString().slice(0, 10);
}

function mensaje(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "No pudimos anotarte. Probá de nuevo en unos minutos.";
  }
  const telefono =
    typeof error.extra.clinic_phone === "string" ? ` al ${error.extra.clinic_phone}` : "";
  const textos: Record<string, string> = {
    already_waiting: `Ya estás en la lista de espera para ese profesional. Si querés cambiar algo, comunicate con la clínica${telefono}.`,
    rate_limited: "Hiciste muchos intentos seguidos. Esperá un momento y probá de nuevo: no perdiste lo que cargaste.",
    invalid_range: "Revisá las fechas: el período tiene que empezar hoy o después y terminar después de empezar.",
    range_too_large: "El período es demasiado largo: elegí uno más corto.",
    invalid_time_window: "Completá la franja con hora de inicio y de fin, en ese orden.",
    contact_required: "Dejanos un teléfono o un email para avisarte.",
    whatsapp_opt_in_required: "Indicá si querés recibir avisos por WhatsApp o dejanos un email.",
    privacy_consent_required: "Tenés que aceptar la política de privacidad.",
    network_error: "No hay conexión. Revisá tu internet y probá de nuevo."
  };
  return textos[error.detail] ?? "No pudimos anotarte. Probá de nuevo en unos minutos.";
}

interface WaitlistStepProps {
  slug: string;
  catalog: BookingCatalog;
  professionalId: string | null;
  today: string;
  onCancel: () => void;
}

function WaitlistStep({ slug, catalog, professionalId, today, onCancel }: WaitlistStepProps): JSX.Element {
  const id = useId();
  const [profesional, setProfesional] = useState(professionalId ?? "");
  const [desde, setDesde] = useState(today);
  const [hasta, setHasta] = useState(sumarDias(today, 14));
  const [franjaDesde, setFranjaDesde] = useState("");
  const [franjaHasta, setFranjaHasta] = useState("");
  const [dias, setDias] = useState<number[]>([]);
  const [hecho, setHecho] = useState<WaitlistJoined | null>(null);
  const anotar = useMutation({
    mutationFn: (patient: BookingPatient) =>
      joinWaitlist(slug, {
        professional_id: profesional === "" ? null : profesional,
        date_from: desde,
        date_to: hasta,
        time_from: franjaDesde === "" ? null : franjaDesde,
        time_to: franjaHasta === "" ? null : franjaHasta,
        weekdays: dias.length > 0 ? dias : null,
        patient
      }),
    onSuccess: setHecho
  });

  if (hecho !== null) {
    const nombre =
      catalog.professionals.find((p) => p.id === hecho.professional_id)?.display_name ?? "cualquier profesional";
    return (
      <div role="status" className="mt-4 rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm">
        <p className="font-semibold">Te anotamos en la lista de espera</p>
        <p className="mt-1">
          Con {nombre}, del {hecho.date_from.split("-").reverse().slice(0, 2).join("/")} al{" "}
          {hecho.date_to.split("-").reverse().slice(0, 2).join("/")}.
        </p>
        <p className="mt-1">
          Si se libera un turno que te sirva, te avisamos por {hecho.channel === "whatsapp" ? "WhatsApp" : "email"}{" "}
          con un link para tomarlo antes de que venza.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-4">
      <p className="text-sm">
        Contanos cuándo te sirve y te avisamos si se libera un turno.
      </p>
      <div className="mt-3 flex flex-col gap-3">
        <div>
          <label htmlFor={`${id}-prof`} className="text-sm font-medium">
            Profesional
          </label>
          <select id={`${id}-prof`} className={INPUT} value={profesional} onChange={(e) => setProfesional(e.target.value)}>
            <option value="">Cualquiera</option>
            {catalog.professionals.map((p) => (
              <option key={p.id} value={p.id}>
                {p.display_name}
              </option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor={`${id}-desde`} className="text-sm font-medium">
              Desde
            </label>
            <input id={`${id}-desde`} type="date" className={INPUT} value={desde} onChange={(e) => setDesde(e.target.value)} />
          </div>
          <div>
            <label htmlFor={`${id}-hasta`} className="text-sm font-medium">
              Hasta
            </label>
            <input id={`${id}-hasta`} type="date" className={INPUT} value={hasta} onChange={(e) => setHasta(e.target.value)} />
          </div>
          <div>
            <label htmlFor={`${id}-fd`} className="text-sm font-medium">
              Desde las (opcional)
            </label>
            <input id={`${id}-fd`} type="time" className={INPUT} value={franjaDesde} onChange={(e) => setFranjaDesde(e.target.value)} />
          </div>
          <div>
            <label htmlFor={`${id}-fh`} className="text-sm font-medium">
              Hasta las (opcional)
            </label>
            <input id={`${id}-fh`} type="time" className={INPUT} value={franjaHasta} onChange={(e) => setFranjaHasta(e.target.value)} />
          </div>
        </div>
        <fieldset>
          <legend className="text-sm font-medium">Días que te sirven (opcional)</legend>
          <div className="mt-1 flex flex-wrap gap-2">
            {DIAS.map((nombre, dia) => (
              <label key={nombre} className="flex min-h-11 items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  className="h-5 w-5 accent-dental-700"
                  checked={dias.includes(dia)}
                  onChange={() =>
                    setDias((actual) =>
                      actual.includes(dia) ? actual.filter((d) => d !== dia) : [...actual, dia].sort()
                    )
                  }
                />
                {nombre}
              </label>
            ))}
          </div>
        </fieldset>
      </div>
      {anotar.isError && (
        <p role="alert" className="mt-4 rounded border border-rose-700/40 bg-rose-50 p-3 text-sm">
          {mensaje(anotar.error)}
        </p>
      )}
      <ContactStep
        timezone={catalog.timezone}
        pending={anotar.isPending}
        problem={null}
        submitLabel="Anotarme en la lista de espera"
        pendingLabel="Anotando…"
        onSubmit={(patient) => anotar.mutate(patient)}
        onPickAlternative={() => undefined}
        onChooseAnother={onCancel}
      />
      <button type="button" className={`${CHOICE} ${CHOICE_OFF} mt-3 w-full`} onClick={onCancel}>
        Volver a los horarios
      </button>
    </div>
  );
}

export default WaitlistStep;
