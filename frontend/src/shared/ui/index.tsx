/**
 * Kit de UI mínimo de la clínica (Tailwind + tokens `dental`/`enamel`).
 * Accesible por defecto: labels asociados, `role="alert"` en errores, foco visible.
 */
import {
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes
} from "react";

type Variant = "primary" | "secondary" | "danger" | "ghost";

const VARIANTES: Record<Variant, string> = {
  primary: "bg-dental-600 text-white hover:bg-dental-700 disabled:bg-dental-600/50",
  secondary:
    "border border-dental-600/40 bg-white text-dental-900 hover:bg-dental-50 disabled:opacity-50",
  danger: "bg-rose-700 text-white hover:bg-rose-800 disabled:bg-rose-700/50",
  ghost: "text-dental-900 hover:bg-dental-50 disabled:opacity-50"
};

export function Button({
  variant = "primary",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }): JSX.Element {
  return (
    <button
      type={type}
      className={`rounded px-3 py-1.5 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-dental-600 disabled:cursor-not-allowed ${VARIANTES[variant]} ${className}`}
      {...props}
    />
  );
}

const CAMPO =
  "mt-1 block w-full rounded border border-dental-600/30 bg-white px-2 py-1.5 text-sm focus:border-dental-600 focus:outline-none focus:ring-1 focus:ring-dental-600";

export function TextField({
  label,
  hint,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }): JSX.Element {
  const id = useId();
  const hintId = `${id}-hint`;
  return (
    <div className="block text-sm">
      <label htmlFor={id} className="font-medium">
        {label}
      </label>
      <input
        id={id}
        className={CAMPO}
        aria-describedby={hint !== undefined ? hintId : undefined}
        {...props}
      />
      {hint !== undefined && (
        <span id={hintId} className="mt-0.5 block text-xs opacity-70">
          {hint}
        </span>
      )}
    </div>
  );
}

export function TextArea({
  label,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string }): JSX.Element {
  const id = useId();
  return (
    <label htmlFor={id} className="block text-sm">
      <span className="font-medium">{label}</span>
      <textarea id={id} className={CAMPO} rows={2} {...props} />
    </label>
  );
}

export function SelectField({
  label,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string; children: ReactNode }): JSX.Element {
  const id = useId();
  return (
    <label htmlFor={id} className="block text-sm">
      <span className="font-medium">{label}</span>
      <select id={id} className={CAMPO} {...props}>
        {children}
      </select>
    </label>
  );
}

export function Alert({
  children,
  tone = "error"
}: {
  children: ReactNode;
  tone?: "error" | "info" | "success";
}): JSX.Element {
  const tonos = {
    error: "border-rose-300 bg-rose-50 text-rose-900",
    info: "border-sky-300 bg-sky-50 text-sky-900",
    success: "border-emerald-300 bg-emerald-50 text-emerald-900"
  };
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`rounded border px-3 py-2 text-sm ${tonos[tone]}`}>
      {children}
    </div>
  );
}

/** Diálogo modal accesible: título, cierre con Escape y foco inicial. */
export function Modal({
  title,
  onClose,
  children
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}): JSX.Element {
  const titleId = useId();
  const ref = useRef<HTMLDivElement>(null);
  const cerrar = useRef(onClose);
  cerrar.current = onClose;
  // Foco inicial solo al montar: `onClose` cambia de identidad en cada render y
  // re-enfocar el diálogo le robaría el foco al campo que se está escribiendo.
  useEffect(() => {
    ref.current?.focus();
    const onKey = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        cerrar.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div className="fixed inset-0 z-20 flex items-start justify-center overflow-y-auto bg-dental-900/40 p-4">
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="mt-10 w-full max-w-lg rounded-lg bg-white p-5 shadow-xl focus:outline-none"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <h2 id={titleId} className="text-lg font-semibold text-dental-900">
            {title}
          </h2>
          <Button variant="ghost" aria-label="Cerrar" onClick={onClose}>
            ✕
          </Button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function PageTitle({ children, actions }: { children: ReactNode; actions?: ReactNode }): JSX.Element {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
      <h1 className="text-xl font-semibold text-dental-900">{children}</h1>
      {actions}
    </div>
  );
}
