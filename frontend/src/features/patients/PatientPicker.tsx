/**
 * Búsqueda de pacientes por nombre o teléfono + alta rápida (US-011 CA-1).
 * La búsqueda espera 300 ms y al menos 3 caracteres (mismo mínimo que la API).
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { ApiError, apiFetch } from "../../shared/api/client";
import { messageFor } from "../../shared/api/errors";
import type { Patient, PatientCreate, PatientDetail } from "../../shared/api/types";
import { Alert, Button, TextField } from "../../shared/ui";

export interface PickedPatient {
  id: string;
  full_name: string;
}

function useDebounced(value: string, ms: number): string {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}

export function PatientSearch({
  label = "Buscar paciente",
  onPick,
  excludeId,
  allowCreate = true
}: {
  label?: string;
  onPick: (patient: PickedPatient) => void;
  excludeId?: string;
  allowCreate?: boolean;
}): JSX.Element {
  const [q, setQ] = useState("");
  const [creando, setCreando] = useState(false);
  const termino = useDebounced(q.trim(), 300);
  const busqueda = useQuery({
    queryKey: ["patients", termino],
    queryFn: () =>
      apiFetch<{ items: Patient[] }>("/api/patients", { query: { q: termino } }).then((r) => r.items),
    enabled: termino.length >= 3
  });
  const resultados = (busqueda.data ?? []).filter((p) => p.id !== excludeId);

  return (
    <div className="space-y-2">
      <TextField
        label={label}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Nombre o teléfono"
        hint="Mínimo 3 caracteres."
      />
      {termino.length >= 3 && busqueda.isSuccess && resultados.length === 0 && (
        <p className="text-sm opacity-70">Sin resultados</p>
      )}
      {busqueda.isError && <Alert>{messageFor(busqueda.error)}</Alert>}
      {resultados.length > 0 && (
        <ul className="max-h-48 divide-y overflow-y-auto rounded border border-dental-600/20">
          {resultados.map((p) => (
            <li key={p.id} className="flex items-center justify-between gap-2 px-2 py-1 text-sm">
              <span>
                {p.full_name}
                <span className="ml-2 text-xs opacity-70">{p.phone_e164 ?? p.email ?? ""}</span>
              </span>
              <Button variant="secondary" aria-label={`Elegir ${p.full_name}`} onClick={() => onPick(p)}>
                Elegir
              </Button>
            </li>
          ))}
        </ul>
      )}
      {allowCreate &&
        (creando ? (
          <QuickCreate onCreated={onPick} onCancel={() => setCreando(false)} />
        ) : (
          <Button variant="ghost" onClick={() => setCreando(true)}>
            Paciente nuevo
          </Button>
        ))}
    </div>
  );
}

function QuickCreate({
  onCreated,
  onCancel
}: {
  onCreated: (patient: PickedPatient) => void;
  onCancel: () => void;
}): JSX.Element {
  const [nombre, setNombre] = useState("");
  const [telefono, setTelefono] = useState("");
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [duplicado, setDuplicado] = useState<string | null>(null);

  async function crear(): Promise<void> {
    setError(null);
    setDuplicado(null);
    const body: PatientCreate = { full_name: nombre.trim() };
    if (telefono.trim() !== "") {
      body.phone = telefono.trim();
    }
    if (email.trim() !== "") {
      body.email = email.trim();
    }
    try {
      const creado = await apiFetch<Patient>("/api/patients", { method: "POST", body });
      onCreated(creado);
    } catch (e) {
      const id = e instanceof ApiError ? e.extra.patient_id : undefined;
      if (e instanceof ApiError && e.detail === "patient_duplicate" && typeof id === "string") {
        setDuplicado(id);
      }
      setError(messageFor(e));
    }
  }

  async function usarExistente(id: string): Promise<void> {
    try {
      const existente = await apiFetch<PatientDetail>(`/api/patients/${id}`);
      onCreated(existente);
    } catch (e) {
      setError(messageFor(e));
    }
  }

  return (
    <fieldset className="space-y-2 rounded border border-dental-600/20 p-3">
      <legend className="px-1 text-sm font-medium">Paciente nuevo</legend>
      <TextField label="Nombre y apellido" value={nombre} onChange={(e) => setNombre(e.target.value)} />
      <TextField label="Teléfono" value={telefono} onChange={(e) => setTelefono(e.target.value)} />
      <TextField label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      {error !== null && <Alert>{error}</Alert>}
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => void crear()} disabled={nombre.trim() === ""}>
          Crear paciente
        </Button>
        {duplicado !== null && (
          <Button variant="secondary" onClick={() => void usarExistente(duplicado)}>
            Usar el paciente existente
          </Button>
        )}
        <Button variant="ghost" onClick={onCancel}>
          Cancelar
        </Button>
      </div>
    </fieldset>
  );
}
