import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { server } from "../../test/server";
import { ApiError, apiFetch, configureApi, resetApiConfig } from "./client";

function configurar(token: string | null, refresh: () => Promise<string | null>) {
  const onUnauthorized = vi.fn();
  let actual = token;
  configureApi({
    getAccess: () => actual,
    refresh: async () => {
      actual = await refresh();
      return actual;
    },
    onUnauthorized
  });
  return { onUnauthorized };
}

afterEach(() => resetApiConfig());

describe("cliente API", () => {
  it("manda el bearer de memoria y parsea JSON", async () => {
    configurar("acceso-1", async () => null);
    server.use(
      http.get("/api/clinic", ({ request }) =>
        HttpResponse.json({ auth: request.headers.get("Authorization") })
      )
    );
    await expect(apiFetch<{ auth: string }>("/api/clinic")).resolves.toEqual({
      auth: "Bearer acceso-1"
    });
  });

  it("serializa query con valores repetidos y omite vacíos", async () => {
    configurar("acceso-1", async () => null);
    server.use(
      http.get("/api/appointments", ({ request }) =>
        HttpResponse.json({ q: new URL(request.url).search })
      )
    );
    const r = await apiFetch<{ q: string }>("/api/appointments", {
      query: { status: ["pending", "confirmed"], chair_id: undefined, limit: 500 }
    });
    expect(r.q).toBe("?status=pending&status=confirmed&limit=500");
  });

  it("un error de dominio trae status, detail y extras", async () => {
    configurar("acceso-1", async () => null);
    server.use(
      http.post("/api/appointments", () =>
        HttpResponse.json(
          { detail: "slot_taken", conflicts: ["a"], alternatives: [] },
          { status: 409 }
        )
      )
    );
    const error = await apiFetch("/api/appointments", { method: "POST", body: {} }).catch(
      (e: unknown) => e
    );
    expect(error).toBeInstanceOf(ApiError);
    const apiError = error as ApiError;
    expect(apiError.status).toBe(409);
    expect(apiError.detail).toBe("slot_taken");
    expect(apiError.extra).toEqual({ conflicts: ["a"], alternatives: [] });
  });

  it("un 422 de validación con lista de errores se resume como validation_error", async () => {
    configurar("acceso-1", async () => null);
    server.use(
      http.post("/api/patients", () =>
        HttpResponse.json({ detail: [{ loc: ["body"], msg: "x" }] }, { status: 422 })
      )
    );
    const error = (await apiFetch("/api/patients", { method: "POST", body: {} }).catch(
      (e: unknown) => e
    )) as ApiError;
    expect(error.detail).toBe("validation_error");
  });

  it("ante 401 vencido renueva una vez y reintenta", async () => {
    const refresh = vi.fn(async () => "acceso-2");
    configurar("acceso-1", refresh);
    server.use(
      http.get("/api/clinic", ({ request }) =>
        request.headers.get("Authorization") === "Bearer acceso-2"
          ? HttpResponse.json({ ok: true })
          : HttpResponse.json({ detail: "token_expired" }, { status: 401 })
      )
    );
    await expect(apiFetch("/api/clinic")).resolves.toEqual({ ok: true });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("reintenta una sola vez aunque el segundo intento también dé 401", async () => {
    const refresh = vi.fn(async () => "acceso-2");
    configurar("acceso-1", refresh);
    server.use(
      http.get("/api/clinic", () =>
        HttpResponse.json({ detail: "token_expired" }, { status: 401 })
      )
    );
    await expect(apiFetch("/api/clinic")).rejects.toMatchObject({ status: 401 });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("si la renovación falla avisa para cerrar la sesión", async () => {
    const { onUnauthorized } = configurar("acceso-1", async () => null);
    server.use(
      http.get("/api/clinic", () =>
        HttpResponse.json({ detail: "token_expired" }, { status: 401 })
      )
    );
    await expect(apiFetch("/api/clinic")).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("un 401 que no es de token (clave actual incorrecta) no renueva", async () => {
    const refresh = vi.fn(async () => "acceso-2");
    configurar("acceso-1", refresh);
    server.use(
      http.post("/api/auth/change-password", () =>
        HttpResponse.json({ detail: "invalid_credentials" }, { status: 401 })
      )
    );
    await expect(
      apiFetch("/api/auth/change-password", { method: "POST", body: {} })
    ).rejects.toMatchObject({ detail: "invalid_credentials" });
    expect(refresh).not.toHaveBeenCalled();
  });

  it("los endpoints públicos de auth no disparan renovación", async () => {
    const refresh = vi.fn(async () => "acceso-2");
    configurar(null, refresh);
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json({ detail: "invalid_credentials" }, { status: 401 })
      )
    );
    await expect(
      apiFetch("/api/auth/login", { method: "POST", body: {}, auth: false })
    ).rejects.toMatchObject({ detail: "invalid_credentials" });
    expect(refresh).not.toHaveBeenCalled();
  });

  it("204 devuelve undefined y la caída de red es network_error", async () => {
    configurar("acceso-1", async () => null);
    server.use(
      http.delete("/api/blocks/1", () => new HttpResponse(null, { status: 204 })),
      http.get("/api/chairs", () => HttpResponse.error())
    );
    await expect(apiFetch("/api/blocks/1", { method: "DELETE" })).resolves.toBeUndefined();
    await expect(apiFetch("/api/chairs")).rejects.toMatchObject({
      status: 0,
      detail: "network_error"
    });
  });

  it("expone Retry-After de un 429", async () => {
    configurar(null, async () => null);
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json(
          { detail: "rate_limited" },
          { status: 429, headers: { "Retry-After": "30" } }
        )
      )
    );
    const error = (await apiFetch("/api/auth/login", {
      method: "POST",
      body: {},
      auth: false
    }).catch((e: unknown) => e)) as ApiError;
    expect(error.retryAfterSeconds).toBe(30);
  });
});
