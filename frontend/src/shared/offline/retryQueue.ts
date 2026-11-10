/**
 * Cola de reintentos de recepción (C-14, D11; SU-06, Open Decision 3).
 *
 * Solo para cambios que ya pasaron en el mundo real y que repetir no rompe: confirmar un turno y
 * registrar asistencia. Alta, reprogramación y cancelación NO se encolan (necesitan el estado vivo
 * de la agenda y disparan lista de espera y recordatorios).
 *
 * En memoria a propósito: nada con datos del paciente queda en `localStorage` (regla 13). Si se
 * cierra la pestaña sin red, lo encolado se pierde; el indicador lo avisa.
 *
 * Un `409 invalid_transition` al reintentar se toma como "ya aplicado" (otra persona lo hizo).
 */
import { useSyncExternalStore } from "react";
import { ApiError } from "../api/client";
import { isRetryable, retryDelay } from "../api/retry";

export const MAX_ATTEMPTS = 5;
export const MAX_AGE_MS = 30 * 60_000;
const ALREADY_APPLIED = new Set(["invalid_transition"]);

export type QueuedStatus = "pending" | "sending" | "done" | "failed";

export interface QueuedChange {
  id: string;
  /** Texto para recepción, sin datos de contacto (p. ej. "Presente · 10:30 · Sillón 1"). */
  label: string;
  status: QueuedStatus;
  attempts: number;
  createdAt: number;
  nextAt: number;
  error: string | null;
}

interface Entry extends QueuedChange {
  run: () => Promise<unknown>;
  onDone?: () => void;
}

type Listener = () => void;

export interface RetryQueueOptions {
  now?: () => number;
  random?: () => number;
}

export interface RetryQueue {
  enqueue(change: { id: string; label: string; run: () => Promise<unknown>; onDone?: () => void }): void;
  flush(force?: boolean): Promise<void>;
  dismiss(id: string): void;
  clear(): void;
  getSnapshot(): readonly QueuedChange[];
  subscribe(listener: Listener): () => void;
}

export function createRetryQueue(options: RetryQueueOptions = {}): RetryQueue {
  const now = options.now ?? Date.now;
  const random = options.random ?? Math.random;
  const entries = new Map<string, Entry>();
  const listeners = new Set<Listener>();
  let snapshot: readonly QueuedChange[] = [];

  function publish(): void {
    snapshot = [...entries.values()].map((e) => ({
      id: e.id,
      label: e.label,
      status: e.status,
      attempts: e.attempts,
      createdAt: e.createdAt,
      nextAt: e.nextAt,
      error: e.error
    }));
    for (const listener of listeners) {
      listener();
    }
  }

  async function attempt(entry: Entry): Promise<void> {
    entry.status = "sending";
    entry.attempts += 1;
    publish();
    try {
      await entry.run();
      entry.status = "done";
      entry.error = null;
      entry.onDone?.();
    } catch (error) {
      if (error instanceof ApiError && ALREADY_APPLIED.has(error.detail)) {
        entry.status = "done";
        entry.error = null;
        entry.onDone?.();
      } else if (
        isRetryable(error) &&
        entry.attempts < MAX_ATTEMPTS &&
        now() - entry.createdAt < MAX_AGE_MS
      ) {
        entry.status = "pending";
        entry.nextAt = now() + retryDelay(entry.attempts - 1, error, random);
        entry.error = error instanceof ApiError ? error.detail : "error";
      } else {
        entry.status = "failed";
        entry.error = error instanceof ApiError ? error.detail : "error";
      }
    }
    publish();
  }

  return {
    /** Encola un cambio (si ya hay uno con el mismo id, lo reemplaza: vale el último clic). */
    enqueue(change: { id: string; label: string; run: () => Promise<unknown>; onDone?: () => void }): void {
      const t = now();
      entries.set(change.id, {
        ...change,
        status: "pending",
        attempts: 0,
        createdAt: t,
        nextAt: t + retryDelay(0, undefined, random),
        error: null
      });
      publish();
    },
    /** Reintenta lo vencido (`force`: todo lo pendiente, p. ej. al volver la red). */
    async flush(force = false): Promise<void> {
      const t = now();
      const vencidos = [...entries.values()].filter(
        (e) => e.status === "pending" && (force || e.nextAt <= t)
      );
      for (const entry of vencidos) {
        await attempt(entry);
      }
    },
    /** Saca de la vista lo terminado o fallido que recepción ya leyó. */
    dismiss(id: string): void {
      const entry = entries.get(id);
      if (entry !== undefined && entry.status !== "sending") {
        entries.delete(id);
        publish();
      }
    },
    clear(): void {
      entries.clear();
      publish();
    },
    getSnapshot(): readonly QueuedChange[] {
      return snapshot;
    },
    subscribe(listener: Listener): () => void {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    }
  };
}

/** Cola de la pestaña (una por SPA). */
export const retryQueue: RetryQueue = createRetryQueue();

export function useRetryQueue(queue: RetryQueue = retryQueue): readonly QueuedChange[] {
  return useSyncExternalStore(queue.subscribe, queue.getSnapshot, queue.getSnapshot);
}

/** Programa los reintentos: cada `intervalMs` y al volver la red. Devuelve el cleanup. */
export function startRetryLoop(queue: RetryQueue = retryQueue, intervalMs = 15_000, target: Window = window): () => void {
  const tick = (): void => {
    void queue.flush();
  };
  const alVolver = (): void => {
    void queue.flush(true);
  };
  const id = target.setInterval(tick, intervalMs);
  target.addEventListener("online", alVolver);
  return () => {
    target.clearInterval(id);
    target.removeEventListener("online", alVolver);
  };
}
