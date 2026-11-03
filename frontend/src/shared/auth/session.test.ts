import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "../../test/server";
import type { UserProfile } from "../api/types";
import { createSession, type ChannelLike, type LockManagerLike } from "./session";

const USUARIO: UserProfile = {
  id: "u-1",
  email: "recepcion.ficticia@example.com",
  role: "recepcion",
  clinic_id: "c-1",
  professional_id: null,
  must_change_password: false,
  last_login_at: null
};

/** Lock por nombre que serializa como `navigator.locks` (exclusivo). */
function fakeLocks(): LockManagerLike {
  const colas = new Map<string, Promise<unknown>>();
  return {
    request: <T>(name: string, callback: () => Promise<T>): Promise<T> => {
      const previa = colas.get(name) ?? Promise.resolve();
      const actual = previa.then(callback, callback);
      colas.set(
        name,
        actual.catch(() => undefined)
      );
      return actual;
    }
  };
}

/** Bus tipo `BroadcastChannel`: entrega asíncrona a las demás pestañas, no a sí misma. */
function fakeBus(): () => ChannelLike {
  const canales = new Set<ChannelLike>();
  return () => {
    const canal: ChannelLike = {
      onmessage: null,
      postMessage(data: unknown) {
        for (const otro of canales) {
          if (otro !== canal) {
            setTimeout(() => otro.onmessage?.({ data } as MessageEvent), 0);
          }
        }
      },
      close() {
        canales.delete(canal);
      }
    };
    canales.add(canal);
    return canal;
  };
}

function contarRefresh(respuesta: () => Response) {
  const contador = { n: 0 };
  server.use(
    http.post("/api/auth/refresh", () => {
      contador.n += 1;
      return respuesta();
    }),
    http.get("/api/auth/me", () => HttpResponse.json(USUARIO))
  );
  return contador;
}

const tokenNuevo = (n = 2) => () =>
  HttpResponse.json({ access_token: `acceso-${n}`, token_type: "bearer", expires_in: 900 });

describe("sesión del personal", () => {
  it("el login guarda el access solo en memoria", async () => {
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json({
          access_token: "acceso-1",
          token_type: "bearer",
          expires_in: 900,
          user: USUARIO
        })
      )
    );
    const sesion = createSession({ locks: fakeLocks(), channel: fakeBus()() });

    await sesion.login("recepcion.ficticia@example.com", "clave-ficticia-larga");

    expect(sesion.getAccess()).toBe("acceso-1");
    expect(sesion.getState()).toEqual({ status: "authenticated", user: USUARIO });
    expect(JSON.stringify({ ...localStorage })).not.toContain("acceso-1");
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("acceso-1");
  });

  it("tres renovaciones simultáneas en una pestaña envían un solo refresh", async () => {
    const contador = contarRefresh(tokenNuevo());
    const sesion = createSession({ locks: fakeLocks(), channel: fakeBus()() });

    const tokens = await Promise.all([
      sesion.refreshAccess(),
      sesion.refreshAccess(),
      sesion.refreshAccess()
    ]);

    expect(tokens).toEqual(["acceso-2", "acceso-2", "acceso-2"]);
    expect(contador.n).toBe(1);
  });

  it("dos pestañas que renuevan a la vez envían un solo refresh", async () => {
    const contador = contarRefresh(tokenNuevo());
    const locks = fakeLocks();
    const bus = fakeBus();
    const pestanaA = createSession({ locks, channel: bus() });
    const pestanaB = createSession({ locks, channel: bus() });

    const [a, b] = await Promise.all([pestanaA.refreshAccess(), pestanaB.refreshAccess()]);

    expect(a).toBe("acceso-2");
    expect(b).toBe("acceso-2");
    expect(contador.n).toBe(1);
  });

  it("refresh rechazado cierra la sesión en todas las pestañas", async () => {
    contarRefresh(() => HttpResponse.json({ detail: "refresh_reuse" }, { status: 401 }));
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json({
          access_token: "acceso-1",
          token_type: "bearer",
          expires_in: 900,
          user: USUARIO
        })
      )
    );
    const locks = fakeLocks();
    const bus = fakeBus();
    const pestanaA = createSession({ locks, channel: bus() });
    const pestanaB = createSession({ locks, channel: bus() });
    await pestanaA.login("x@example.com", "clave-ficticia-larga");
    await pestanaB.login("x@example.com", "clave-ficticia-larga");
    await new Promise((r) => setTimeout(r, 10));

    await expect(pestanaA.refreshAccess()).resolves.toBeNull();
    await new Promise((r) => setTimeout(r, 10));

    expect(pestanaA.getState().status).toBe("anonymous");
    expect(pestanaB.getState().status).toBe("anonymous");
    expect(pestanaB.getAccess()).toBeNull();
  });

  it("sin navigator.locks igual deduplica dentro de la pestaña", async () => {
    const contador = contarRefresh(tokenNuevo());
    const sesion = createSession({ locks: null, channel: null });

    await Promise.all([sesion.refreshAccess(), sesion.refreshAccess()]);

    expect(contador.n).toBe(1);
  });

  it("el arranque recupera la sesión con la cookie y carga el perfil", async () => {
    contarRefresh(tokenNuevo(5));
    const sesion = createSession({ locks: fakeLocks(), channel: fakeBus()() });

    await sesion.bootstrap();

    expect(sesion.getAccess()).toBe("acceso-5");
    expect(sesion.getState()).toEqual({ status: "authenticated", user: USUARIO });
  });

  it("el arranque sin cookie queda anónimo", async () => {
    contarRefresh(() => HttpResponse.json({ detail: "invalid_refresh" }, { status: 401 }));
    const sesion = createSession({ locks: fakeLocks(), channel: fakeBus()() });

    await sesion.bootstrap();

    expect(sesion.getState()).toEqual({ status: "anonymous", user: null });
  });

  it("logout descarta la sesión aunque la API no responda", async () => {
    contarRefresh(tokenNuevo());
    server.use(http.post("/api/auth/logout", () => HttpResponse.error()));
    const bus = fakeBus();
    const locks = fakeLocks();
    const pestanaA = createSession({ locks, channel: bus() });
    const pestanaB = createSession({ locks, channel: bus() });
    await pestanaA.bootstrap();
    await pestanaB.bootstrap();

    await pestanaA.logout();
    await new Promise((r) => setTimeout(r, 10));

    expect(pestanaA.getState().status).toBe("anonymous");
    expect(pestanaB.getState().status).toBe("anonymous");
  });

  it("notifica a los suscriptores", async () => {
    contarRefresh(tokenNuevo());
    const sesion = createSession({ locks: fakeLocks(), channel: fakeBus()() });
    const estados: string[] = [];
    sesion.subscribe((s) => estados.push(s.status));

    await sesion.bootstrap();

    expect(estados).toContain("authenticated");
  });
});
