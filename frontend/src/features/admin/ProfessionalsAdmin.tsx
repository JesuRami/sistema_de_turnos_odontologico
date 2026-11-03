/** Profesionales (US-001): alta, edición y baja lógica. Nunca se borran (regla 7). */
import { useState, type FormEvent } from "react";
import { apiFetch } from "../../shared/api/client";
import { queryKeys, useProfessionals } from "../../shared/api/queries";
import type { Professional } from "../../shared/api/types";
import { Alert, Button, Modal, PageTitle, TextField } from "../../shared/ui";
import { colorFor } from "../agenda/layout";
import { changedFields, useSave } from "./useSave";

interface Datos {
  display_name: string;
  color: string;
  default_duration_min: number;
  buffer_min: number;
  booking_enabled: boolean;
}

const VACIO: Datos = { display_name: "", color: "", default_duration_min: 30, buffer_min: 0, booking_enabled: true };

function datosDe(p: Professional): Datos {
  return {
    display_name: p.display_name,
    color: p.color ?? "",
    default_duration_min: p.default_duration_min,
    buffer_min: p.buffer_min,
    booking_enabled: p.booking_enabled
  };
}

function aBody(d: Datos): Omit<Datos, "color"> & { color: string | null } {
  return { ...d, display_name: d.display_name.trim(), color: d.color.trim() === "" ? null : d.color.trim() };
}

function ProfessionalsAdmin(): JSX.Element {
  const professionals = useProfessionals();
  const save = useSave([queryKeys.professionals]);
  const [editando, setEditando] = useState<Professional | "nuevo" | null>(null);

  return (
    <section>
      <PageTitle actions={<Button onClick={() => setEditando("nuevo")}>Nuevo profesional</Button>}>
        Profesionales
      </PageTitle>
      {save.error !== null && editando === null && <Alert>{save.error}</Alert>}
      <table className="w-full rounded bg-white text-sm shadow-sm">
        <thead className="bg-dental-50 text-left">
          <tr>
            <th className="px-2 py-1">Nombre</th>
            <th className="px-2 py-1">Duración</th>
            <th className="px-2 py-1">Buffer</th>
            <th className="px-2 py-1">Reserva online</th>
            <th className="px-2 py-1">Estado</th>
            <th className="px-2 py-1">
              <span className="sr-only">Acciones</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {(professionals.data ?? []).map((p) => (
            <tr key={p.id} className="border-t border-dental-600/10">
              <td className="px-2 py-1">
                <span className="mr-2 inline-block h-3 w-3 rounded-full align-middle" style={{ backgroundColor: colorFor(p) }} />
                {p.display_name}
              </td>
              <td className="px-2 py-1">{p.default_duration_min} min</td>
              <td className="px-2 py-1">{p.buffer_min} min</td>
              <td className="px-2 py-1">{p.booking_enabled ? "Sí" : "No"}</td>
              <td className="px-2 py-1">{p.active ? "Activo" : "Inactivo"}</td>
              <td className="space-x-1 px-2 py-1 text-right">
                <Button variant="ghost" aria-label={`Editar ${p.display_name}`} onClick={() => setEditando(p)}>
                  Editar
                </Button>
                <Button
                  variant="secondary"
                  aria-label={`${p.active ? "Desactivar" : "Reactivar"} ${p.display_name}`}
                  onClick={() =>
                    void save.run(() =>
                      apiFetch(`/api/professionals/${p.id}`, { method: "PATCH", body: { active: !p.active } })
                    )
                  }
                >
                  {p.active ? "Desactivar" : "Reactivar"}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {editando !== null && (
        <ProfessionalForm
          inicial={editando === "nuevo" ? null : editando}
          onClose={() => {
            save.clear();
            setEditando(null);
          }}
          onSubmit={async (datos) => {
            const ok = await save.run(() =>
              editando === "nuevo"
                ? apiFetch("/api/professionals", { method: "POST", body: aBody(datos) })
                : apiFetch(`/api/professionals/${editando.id}`, {
                    method: "PATCH",
                    body: changedFields(aBody(datosDe(editando)), aBody(datos))
                  })
            );
            if (ok) {
              setEditando(null);
            }
          }}
          error={save.error}
          pending={save.pending}
        />
      )}
    </section>
  );
}

function ProfessionalForm({
  inicial,
  onClose,
  onSubmit,
  error,
  pending
}: {
  inicial: Professional | null;
  onClose: () => void;
  onSubmit: (datos: Datos) => Promise<void>;
  error: string | null;
  pending: boolean;
}): JSX.Element {
  const [d, setD] = useState<Datos>(inicial !== null ? datosDe(inicial) : VACIO);
  const set = <K extends keyof Datos>(k: K, v: Datos[K]): void => setD((prev) => ({ ...prev, [k]: v }));
  function enviar(e: FormEvent): void {
    e.preventDefault();
    void onSubmit(d);
  }
  return (
    <Modal title={inicial === null ? "Nuevo profesional" : `Editar ${inicial.display_name}`} onClose={onClose}>
      <form onSubmit={enviar} className="space-y-3" noValidate>
        <TextField label="Nombre" value={d.display_name} onChange={(e) => set("display_name", e.target.value)} />
        <TextField label="Color" placeholder="#2563eb" value={d.color} onChange={(e) => set("color", e.target.value)} />
        <div className="grid grid-cols-2 gap-2">
          <TextField
            label="Duración por defecto (min)"
            type="number"
            min={5}
            max={480}
            value={d.default_duration_min}
            onChange={(e) => set("default_duration_min", Number(e.target.value))}
          />
          <TextField
            label="Buffer (min)"
            type="number"
            min={0}
            max={120}
            value={d.buffer_min}
            onChange={(e) => set("buffer_min", Number(e.target.value))}
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={d.booking_enabled} onChange={(e) => set("booking_enabled", e.target.checked)} />
          Acepta reserva online
        </label>
        {error !== null && <Alert>{error}</Alert>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancelar
          </Button>
          <Button type="submit" disabled={pending}>
            Guardar
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default ProfessionalsAdmin;
