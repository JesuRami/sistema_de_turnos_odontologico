/** Sillones (US-001): alta, renombre y baja lógica. Nunca se borran (regla 7). */
import { useState, type FormEvent } from "react";
import { apiFetch } from "../../shared/api/client";
import { queryKeys, useChairs } from "../../shared/api/queries";
import type { Chair } from "../../shared/api/types";
import { Alert, Button, Modal, PageTitle, TextField } from "../../shared/ui";
import { useSave } from "./useSave";

function ChairsAdmin(): JSX.Element {
  const chairs = useChairs();
  const save = useSave([queryKeys.chairs]);
  const [editando, setEditando] = useState<Chair | "nuevo" | null>(null);
  const [nombre, setNombre] = useState("");

  function abrir(c: Chair | "nuevo"): void {
    save.clear();
    setNombre(c === "nuevo" ? "" : c.name);
    setEditando(c);
  }

  async function guardar(e: FormEvent): Promise<void> {
    e.preventDefault();
    if (editando === null) {
      return;
    }
    const body = { name: nombre.trim() };
    const ok = await save.run(() =>
      editando === "nuevo"
        ? apiFetch("/api/chairs", { method: "POST", body })
        : apiFetch(`/api/chairs/${editando.id}`, { method: "PATCH", body })
    );
    if (ok) {
      setEditando(null);
    }
  }

  return (
    <section>
      <PageTitle actions={<Button onClick={() => abrir("nuevo")}>Nuevo sillón</Button>}>Sillones</PageTitle>
      {save.error !== null && editando === null && <Alert>{save.error}</Alert>}
      <table className="w-full rounded bg-white text-sm shadow-sm">
        <thead className="bg-dental-50 text-left">
          <tr>
            <th className="px-2 py-1">Nombre</th>
            <th className="px-2 py-1">Estado</th>
            <th className="px-2 py-1">
              <span className="sr-only">Acciones</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {(chairs.data ?? []).map((c) => (
            <tr key={c.id} className="border-t border-dental-600/10">
              <td className="px-2 py-1">{c.name}</td>
              <td className="px-2 py-1">{c.active ? "Activo" : "Inactivo"}</td>
              <td className="space-x-1 px-2 py-1 text-right">
                <Button variant="ghost" aria-label={`Editar ${c.name}`} onClick={() => abrir(c)}>
                  Editar
                </Button>
                <Button
                  variant="secondary"
                  aria-label={`${c.active ? "Desactivar" : "Reactivar"} ${c.name}`}
                  onClick={() =>
                    void save.run(() => apiFetch(`/api/chairs/${c.id}`, { method: "PATCH", body: { active: !c.active } }))
                  }
                >
                  {c.active ? "Desactivar" : "Reactivar"}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {editando !== null && (
        <Modal title={editando === "nuevo" ? "Nuevo sillón" : `Editar ${editando.name}`} onClose={() => setEditando(null)}>
          <form onSubmit={(e) => void guardar(e)} className="space-y-3" noValidate>
            <TextField label="Nombre" value={nombre} onChange={(e) => setNombre(e.target.value)} />
            {save.error !== null && <Alert>{save.error}</Alert>}
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setEditando(null)}>
                Cancelar
              </Button>
              <Button type="submit" disabled={save.pending}>
                Guardar
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}

export default ChairsAdmin;
