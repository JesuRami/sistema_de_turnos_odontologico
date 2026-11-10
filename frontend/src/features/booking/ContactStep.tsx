import { useId, useState, type FormEvent } from "react";
import { validateEmail, validatePhoneAR } from "../../shared/forms/validators";
import BookingError from "./BookingError";
import { OPT_IN_MESSAGE, type BookingField, type BookingProblem } from "./bookingErrors";
import { CHOICE, CHOICE_ON } from "./ProfessionalStep";
import type { BookingPatient, BookingSlot } from "./types";

interface ContactStepProps {
  timezone: string;
  pending: boolean;
  /** Error devuelto por la API para el último envío. */
  problem: BookingProblem | null;
  onSubmit: (patient: BookingPatient) => void;
  onPickAlternative: (slot: BookingSlot) => void;
  onChooseAnother: () => void;
  /** Texto del botón (C-12: la anotación en la lista de espera reutiliza este paso). */
  submitLabel?: string;
  pendingLabel?: string;
}

const INPUT =
  "mt-1 block min-h-11 w-full rounded-lg border border-dental-600/30 bg-white px-3 text-base focus:border-dental-600 focus:outline-none focus:ring-2 focus:ring-dental-600 aria-[invalid=true]:border-rose-700";

interface FieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "tel" | "email";
  autoComplete: string;
  invalid: boolean;
  hint?: string;
  error?: string;
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  autoComplete,
  invalid,
  hint,
  error
}: FieldProps): JSX.Element {
  const id = useId();
  const note = error ?? hint;
  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        autoComplete={autoComplete}
        aria-invalid={invalid}
        aria-describedby={note === undefined ? undefined : `${id}-note`}
        className={INPUT}
        onChange={(e) => onChange(e.target.value)}
      />
      {note !== undefined && (
        <p id={`${id}-note`} className={`mt-1 text-xs ${error === undefined ? "opacity-70" : "text-rose-800"}`}>
          {note}
        </p>
      )}
    </div>
  );
}

interface CheckProps {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  invalid: boolean;
  error?: string;
}

function Check({ label, checked, onChange, invalid, error }: CheckProps): JSX.Element {
  const id = useId();
  return (
    <div>
      <div className="flex min-h-11 items-start gap-3">
        <input
          id={id}
          type="checkbox"
          checked={checked}
          aria-invalid={invalid}
          className="mt-1 h-5 w-5 accent-dental-700"
          onChange={(e) => onChange(e.target.checked)}
        />
        <label htmlFor={id} className="text-sm leading-6">
          {label}
        </label>
      </div>
      {error !== undefined && <p className="ml-8 text-xs text-rose-800">{error}</p>}
    </div>
  );
}

const SIN_ERRORES: ReadonlySet<BookingField> = new Set();

function ContactStep({
  timezone,
  pending,
  problem,
  onSubmit,
  onPickAlternative,
  onChooseAnother,
  submitLabel = "Confirmar turno",
  pendingLabel = "Reservando…"
}: ContactStepProps): JSX.Element {
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [optIn, setOptIn] = useState(false);
  const [privacy, setPrivacy] = useState(false);
  const [local, setLocal] = useState<ReadonlyMap<BookingField, string>>(new Map());

  const servidor: ReadonlySet<BookingField> =
    problem === null ? SIN_ERRORES : new Set(problem.fields);
  const invalido = (campo: BookingField): boolean => local.has(campo) || servidor.has(campo);

  function validar(): ReadonlyMap<BookingField, string> {
    const errores = new Map<BookingField, string>();
    const tel = phone.trim();
    const mail = email.trim();
    if (name.trim() === "") {
      errores.set("name", "Escribí tu nombre y apellido");
    }
    if (tel === "" && mail === "") {
      errores.set("phone", "Dejanos un teléfono o un email para avisarte");
      errores.set("email", "Dejanos un teléfono o un email para avisarte");
    } else if (tel !== "" && !optIn && mail === "") {
      errores.set("optin", OPT_IN_MESSAGE);
      errores.set("phone", OPT_IN_MESSAGE);
    }
    // C-14 (D11): formato antes de enviar. Con email cargado, un teléfono dudoso no bloquea: la API
    // lo descarta y avisa por email (contrato de C-07, `phone_invalid_email_channel`).
    const mailInvalido = validateEmail(mail);
    if (mailInvalido !== null) {
      errores.set("email", mailInvalido);
    }
    const telInvalido = validatePhoneAR(tel);
    if (telInvalido !== null && mail === "" && !errores.has("phone")) {
      errores.set("phone", telInvalido);
    }
    if (!privacy) {
      errores.set("privacy", "Tenés que aceptar la política de privacidad");
    }
    return errores;
  }

  function enviar(evento: FormEvent): void {
    evento.preventDefault();
    const errores = validar();
    setLocal(errores);
    if (errores.size > 0) {
      return;
    }
    const tel = phone.trim();
    const mail = email.trim();
    onSubmit({
      full_name: name.trim(),
      ...(tel === "" ? {} : { phone: tel, whatsapp_opt_in: optIn }),
      ...(mail === "" ? {} : { email: mail }),
      privacy_accepted: privacy
    });
  }

  const contactoVacio = local.get("phone") === "Dejanos un teléfono o un email para avisarte";

  return (
    <form noValidate onSubmit={enviar} className="mt-4 flex flex-col gap-4">
      <Field
        label="Nombre y apellido"
        value={name}
        onChange={setName}
        autoComplete="name"
        invalid={invalido("name")}
        error={local.get("name")}
      />
      <Field
        label="Teléfono"
        type="tel"
        value={phone}
        onChange={setPhone}
        autoComplete="tel"
        invalid={invalido("phone")}
        hint="Con código de área, por ejemplo 011 15 5555-0123"
        error={contactoVacio ? undefined : local.get("phone")}
      />
      {phone.trim() !== "" && (
        <Check
          label="Quiero recibir recordatorios por WhatsApp"
          checked={optIn}
          onChange={setOptIn}
          invalid={invalido("optin")}
        />
      )}
      <Field
        label="Email"
        type="email"
        value={email}
        onChange={setEmail}
        autoComplete="email"
        invalid={invalido("email")}
        hint="Opcional si dejaste un teléfono"
        error={contactoVacio ? undefined : local.get("email")}
      />
      {contactoVacio && (
        <p className="-mt-2 text-xs text-rose-800">{local.get("phone")}</p>
      )}
      <Check
        label="Acepto la política de privacidad (texto provisorio, pendiente de validación legal)"
        checked={privacy}
        onChange={setPrivacy}
        invalid={invalido("privacy")}
        error={local.get("privacy")}
      />
      {problem !== null && (
        <BookingError
          problem={problem}
          timezone={timezone}
          disabled={pending}
          onPickAlternative={onPickAlternative}
          onChooseAnother={onChooseAnother}
        />
      )}
      <button
        type="submit"
        disabled={pending}
        className={`${CHOICE} ${CHOICE_ON} w-full disabled:opacity-60`}
      >
        {pending ? pendingLabel : submitLabel}
      </button>
    </form>
  );
}

export default ContactStep;
