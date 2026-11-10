/**
 * Estado de la red visto por la app (C-14, D11; SU-06). Store mínimo para `useSyncExternalStore`:
 *
 * - `online`: lo que informa el navegador (`online`/`offline`).
 * - `lastNetworkErrorAt`: el cliente API lo marca cuando `fetch` ni siquiera llega al servidor;
 *   cualquier respuesta posterior (aunque sea un 4xx) lo limpia vía `lastOkAt`.
 *
 * No guarda nada en disco ni datos del paciente (regla 13).
 */
import { useSyncExternalStore } from "react";

export interface NetworkSnapshot {
  online: boolean;
  lastNetworkErrorAt: number | null;
  lastOkAt: number | null;
}

type Listener = () => void;

function navegadorOnline(): boolean {
  return typeof navigator === "undefined" ? true : navigator.onLine;
}

let snapshot: NetworkSnapshot = { online: navegadorOnline(), lastNetworkErrorAt: null, lastOkAt: null };
const listeners = new Set<Listener>();

function emit(next: NetworkSnapshot): void {
  snapshot = next;
  for (const listener of listeners) {
    listener();
  }
}

export const networkStatus = {
  getSnapshot(): NetworkSnapshot {
    return snapshot;
  },
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  reportNetworkError(now: number = Date.now()): void {
    emit({ ...snapshot, lastNetworkErrorAt: now });
  },
  reportOk(now: number = Date.now()): void {
    // Sin cambios no se notifica: esto corre en cada respuesta de la API.
    if (snapshot.lastNetworkErrorAt === null && snapshot.lastOkAt !== null) {
      snapshot = { ...snapshot, lastOkAt: now };
      return;
    }
    emit({ ...snapshot, lastOkAt: now, lastNetworkErrorAt: null });
  },
  setOnline(online: boolean): void {
    if (online !== snapshot.online) {
      emit({ ...snapshot, online });
    }
  },
  /** Solo tests. */
  reset(): void {
    emit({ online: navegadorOnline(), lastNetworkErrorAt: null, lastOkAt: null });
  }
};

/** ¿Hay que avisar? El navegador dice offline o el último pedido no llegó al servidor. */
export function isDisconnected(s: NetworkSnapshot): boolean {
  return !s.online || s.lastNetworkErrorAt !== null;
}

/** Escucha los eventos del navegador; devuelve la función para dejar de escuchar. */
export function installBrowserListeners(target: Window = window): () => void {
  const alVolver = (): void => networkStatus.setOnline(true);
  const alCaer = (): void => networkStatus.setOnline(false);
  target.addEventListener("online", alVolver);
  target.addEventListener("offline", alCaer);
  return () => {
    target.removeEventListener("online", alVolver);
    target.removeEventListener("offline", alCaer);
  };
}

export function useNetworkStatus(): NetworkSnapshot {
  return useSyncExternalStore(networkStatus.subscribe, networkStatus.getSnapshot, networkStatus.getSnapshot);
}
