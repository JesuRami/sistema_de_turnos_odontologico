/**
 * Estados de carga (C-14, D11). El texto accesible queda en el DOM (`sr-only`), así que un lector de
 * pantalla anuncia qué se está cargando y los tests que buscan "Cargando agenda…" siguen andando.
 */

export function Skeleton({
  label,
  rows = 3,
  className = ""
}: {
  label: string;
  rows?: number;
  className?: string;
}): JSX.Element {
  return (
    <div role="status" aria-live="polite" className={`space-y-2 ${className}`}>
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          aria-hidden="true"
          className="h-4 animate-pulse rounded bg-dental-600/10 motion-reduce:animate-none"
          style={{ width: `${100 - ((i * 17) % 40)}%` }}
        />
      ))}
    </div>
  );
}

/** Grilla gris del tamaño aproximado de la agenda mientras llegan clínica, recursos y turnos. */
export function AgendaSkeleton({ label = "Cargando agenda…" }: { label?: string }): JSX.Element {
  return (
    <div role="status" aria-live="polite" className="space-y-3">
      <span className="sr-only">{label}</span>
      <div aria-hidden="true" className="h-7 w-64 animate-pulse rounded bg-dental-600/10 motion-reduce:animate-none" />
      <div aria-hidden="true" className="grid grid-cols-4 gap-2">
        {Array.from({ length: 12 }, (_, i) => (
          <div key={i} className="h-16 animate-pulse rounded bg-dental-600/10 motion-reduce:animate-none" />
        ))}
      </div>
    </div>
  );
}
