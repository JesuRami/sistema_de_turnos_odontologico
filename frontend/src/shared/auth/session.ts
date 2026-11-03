/**
 * Sesión del personal en la SPA (D1).
 *
 * - El access vive SOLO en memoria de la pestaña (regla 10): nada en storage.
 * - Renovación single-flight: una promesa compartida por pestaña y, entre
 *   pestañas del mismo origen, un lock exclusivo (`navigator.locks`). Así nunca
 *   hay dos `POST /api/auth/refresh` en vuelo con la misma cookie (un refresh ya
 *   rotado responde `refresh_reuse` y revoca la familia, contrato de C-03).
 * - La pestaña que renueva difunde el access por `BroadcastChannel`; la que
 *   esperaba el lock y lo recibió no vuelve a renovar. Si igual lo hiciera, es
 *   seguro: el lock ya serializó y la cookie es la rotada.
 * - Un refresh rechazado cierra la sesión en todas las pestañas.
 */
import { ApiError, apiFetch } from "../api/client";
import type { LoginResponse, RefreshResponse, UserProfile } from "../api/types";

export interface LockManagerLike {
  request<T>(name: string, callback: () => Promise<T>): Promise<T>;
}

export interface ChannelLike {
  onmessage: ((event: MessageEvent) => void) | null;
  postMessage(data: unknown): void;
  close(): void;
}

export type SessionStatus = "unknown" | "anonymous" | "authenticated";

export interface SessionState {
  status: SessionStatus;
  user: UserProfile | null;
}

type Message = { type: "session"; access: string; user: UserProfile | null } | { type: "logout" };

const LOCK_NAME = "turnos-auth-refresh";

export interface Session {
  getAccess(): string | null;
  getState(): SessionState;
  subscribe(listener: (state: SessionState) => void): () => void;
  login(email: string, password: string): Promise<UserProfile>;
  bootstrap(): Promise<void>;
  refreshAccess(): Promise<string | null>;
  reloadProfile(): Promise<void>;
  logout(): Promise<void>;
  /** Cierre local (p. ej. refresh rechazado): sin llamar a la API. */
  expire(): void;
}

function isMessage(value: unknown): value is Message {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const tipo = (value as { type?: unknown }).type;
  return tipo === "session" || tipo === "logout";
}

const nextTask = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

export function createSession(env: {
  locks: LockManagerLike | null;
  channel: ChannelLike | null;
}): Session {
  let access: string | null = null;
  let version = 0;
  let state: SessionState = { status: "unknown", user: null };
  let enVuelo: Promise<string | null> | null = null;
  const listeners = new Set<(s: SessionState) => void>();

  const emit = (next: SessionState): void => {
    state = next;
    for (const listener of listeners) {
      listener(state);
    }
  };

  const setAccess = (token: string, user: UserProfile | null): void => {
    access = token;
    version += 1;
    const perfil = user ?? state.user;
    // Sin perfil (arranque) el estado no cambia hasta cargar `/auth/me`: los guards
    // no deben ver una sesión "autenticada" sin rol.
    if (perfil !== null) {
      emit({ status: "authenticated", user: perfil });
    }
  };

  const clearLocal = (): void => {
    access = null;
    version += 1;
    emit({ status: "anonymous", user: null });
  };

  const broadcast = (message: Message): void => {
    env.channel?.postMessage(message);
  };

  if (env.channel !== null) {
    env.channel.onmessage = (event: MessageEvent) => {
      const data: unknown = event.data;
      if (!isMessage(data)) {
        return;
      }
      if (data.type === "session") {
        setAccess(data.access, data.user);
      } else {
        clearLocal();
      }
    };
  }

  const withLock = <T>(callback: () => Promise<T>): Promise<T> =>
    env.locks === null ? callback() : env.locks.request(LOCK_NAME, callback);

  async function doRefresh(): Promise<string | null> {
    const inicio = version;
    return withLock(async () => {
      // Deja entrar los mensajes de la pestaña que tuvo el lock antes.
      await nextTask();
      if (version !== inicio && access !== null) {
        return access;
      }
      try {
        const r = await apiFetch<RefreshResponse>("/api/auth/refresh", {
          method: "POST",
          auth: false
        });
        setAccess(r.access_token, null);
        broadcast({ type: "session", access: r.access_token, user: state.user });
        return r.access_token;
      } catch (error) {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          clearLocal();
          broadcast({ type: "logout" });
          return null;
        }
        throw error;
      }
    });
  }

  async function loadProfile(): Promise<void> {
    if (access === null) {
      return;
    }
    const user = await apiFetch<UserProfile>("/api/auth/me", { accessToken: access });
    emit({ status: "authenticated", user });
  }

  return {
    getAccess: () => access,
    getState: () => state,
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    async login(email, password) {
      const r = await apiFetch<LoginResponse>("/api/auth/login", {
        method: "POST",
        body: { email, password },
        auth: false
      });
      setAccess(r.access_token, r.user);
      broadcast({ type: "session", access: r.access_token, user: r.user });
      return r.user;
    },
    refreshAccess() {
      if (enVuelo === null) {
        enVuelo = doRefresh().finally(() => {
          enVuelo = null;
        });
      }
      return enVuelo;
    },
    async bootstrap() {
      try {
        const token = await this.refreshAccess();
        if (token === null) {
          if (state.status === "unknown") {
            clearLocal();
          }
          return;
        }
        await loadProfile();
      } catch {
        clearLocal();
      }
    },
    reloadProfile: loadProfile,
    async logout() {
      try {
        await apiFetch<undefined>("/api/auth/logout", { method: "POST", auth: false });
      } catch {
        // La sesión local se descarta igual (spec: logout con la API caída).
      }
      clearLocal();
      broadcast({ type: "logout" });
    },
    expire() {
      clearLocal();
      broadcast({ type: "logout" });
    }
  };
}

function browserLocks(): LockManagerLike | null {
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  if (locks === undefined) {
    return null;
  }
  return {
    request: <T>(name: string, callback: () => Promise<T>): Promise<T> =>
      locks.request(name, callback) as Promise<T>
  };
}

function browserChannel(): ChannelLike | null {
  return typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel("turnos-auth");
}

/** Sesión de la app (una por pestaña). */
export const session: Session = createSession({ locks: browserLocks(), channel: browserChannel() });
