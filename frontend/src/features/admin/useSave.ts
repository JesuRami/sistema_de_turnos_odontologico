/** Mutación de administración: llama a la API, invalida claves y expone el error en español. */
import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useState } from "react";
import { messageFor } from "../../shared/api/errors";

export interface Save {
  run: (action: () => Promise<unknown>) => Promise<boolean>;
  error: string | null;
  pending: boolean;
  clear: () => void;
}

export function useSave(invalidate: readonly QueryKey[]): Save {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  return {
    error,
    pending,
    clear: () => setError(null),
    async run(action) {
      setError(null);
      setPending(true);
      try {
        await action();
        await Promise.all(invalidate.map((queryKey) => queryClient.invalidateQueries({ queryKey })));
        return true;
      } catch (e) {
        setError(messageFor(e));
        return false;
      } finally {
        setPending(false);
      }
    }
  };
}

/** Diferencia superficial: solo los campos que cambiaron (PATCH parcial). */
export function changedFields<T extends object>(before: T, after: T): Partial<T> {
  const cambios: Partial<T> = {};
  for (const clave of Object.keys(after) as (keyof T)[]) {
    if (after[clave] !== before[clave]) {
      cambios[clave] = after[clave];
    }
  }
  return cambios;
}
