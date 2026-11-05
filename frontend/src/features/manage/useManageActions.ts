/**
 * Acciones del paciente (C-08, D14): una a la vez. El doble toque se bloquea de forma síncrona
 * (un `ref`, no solo `isPending`, que recién cambia en el próximo render). La vista que devuelve
 * el servidor reemplaza la de la caché: nada se recalcula en el cliente.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { sendManageAction } from "./api";
import { describeManageProblem, type ManageProblem } from "./manageErrors";
import { viewKey } from "./queries";
import type { ManageActionRequest, ManageView } from "./types";

export interface ManageActionsState {
  run: (action: ManageActionRequest) => void;
  pending: boolean;
  problem: ManageProblem | null;
  /** Último resultado exitoso, para el aviso accesible. */
  done: { action: ManageActionRequest["action"]; view: ManageView } | null;
  clear: () => void;
}

export function useManageActions(token: string, windowHours: number): ManageActionsState {
  const queryClient = useQueryClient();
  const enCurso = useRef(false);
  const [problem, setProblem] = useState<ManageProblem | null>(null);
  const [done, setDone] = useState<ManageActionsState["done"]>(null);

  const mutation = useMutation({
    mutationFn: (action: ManageActionRequest) => sendManageAction(token, action),
    onSuccess: (view, action) => {
      queryClient.setQueryData(viewKey(token), view);
      void queryClient.invalidateQueries({ queryKey: ["manage", token, "availability"] });
      setProblem(null);
      setDone({ action: action.action, view });
    },
    onError: (error) => {
      const descripcion = describeManageProblem(error, windowHours);
      setDone(null);
      setProblem(descripcion);
      if (descripcion.stale) {
        void queryClient.invalidateQueries({ queryKey: ["manage", token] });
      }
    }
  });

  // Se libera DESPUÉS del commit del render: si se liberara en `onSettled`, un segundo toque
  // podría caer sobre el botón viejo antes de que React lo saque del DOM.
  useEffect(() => {
    if (!mutation.isPending) {
      enCurso.current = false;
    }
  }, [mutation.isPending]);

  function run(action: ManageActionRequest): void {
    if (enCurso.current) {
      return;
    }
    enCurso.current = true;
    setProblem(null);
    mutation.mutate(action);
  }

  return {
    run,
    pending: mutation.isPending,
    problem,
    done,
    clear: () => {
      setProblem(null);
      setDone(null);
    }
  };
}
