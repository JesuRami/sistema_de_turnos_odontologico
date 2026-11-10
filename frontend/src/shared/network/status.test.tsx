import { act, render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { apiFetch } from "../api/client";
import { server } from "../../test/server";
import { NetworkBanner } from "./NetworkBanner";
import { installBrowserListeners, isDisconnected, networkStatus } from "./status";

describe("estado de red (C-14, SU-06)", () => {
  it("un pedido que no llega al servidor prende el aviso y la próxima respuesta lo apaga", async () => {
    server.use(http.get("/api/chairs", () => HttpResponse.error()));
    await expect(apiFetch("/api/chairs", { auth: false })).rejects.toMatchObject({ detail: "network_error" });
    expect(isDisconnected(networkStatus.getSnapshot())).toBe(true);

    server.use(http.get("/api/chairs", () => HttpResponse.json({ detail: "forbidden_role" }, { status: 403 })));
    await expect(apiFetch("/api/chairs", { auth: false })).rejects.toMatchObject({ status: 403 });
    // Un 4xx también prueba que hay conexión.
    expect(isDisconnected(networkStatus.getSnapshot())).toBe(false);
  });

  it("el banner aparece sin conexión, con la hora del último dato, y desaparece al volver", () => {
    render(<NetworkBanner offlineHint="Los cambios quedan en cola." />);
    expect(screen.queryByText(/Sin conexión/)).not.toBeInTheDocument();

    act(() => {
      networkStatus.reportOk(new Date("2030-01-07T13:05:00Z").getTime());
      networkStatus.reportNetworkError();
    });
    const aviso = screen.getByRole("status");
    expect(aviso).toHaveTextContent("Sin conexión con el servidor");
    expect(aviso).toHaveTextContent("Último dato recibido");
    expect(aviso).toHaveTextContent("Los cambios quedan en cola.");

    act(() => networkStatus.reportOk());
    expect(screen.queryByText(/Sin conexión/)).not.toBeInTheDocument();
  });

  it("escucha los eventos online/offline del navegador", () => {
    const quitar = installBrowserListeners(window);
    act(() => {
      window.dispatchEvent(new Event("offline"));
    });
    expect(networkStatus.getSnapshot().online).toBe(false);
    act(() => {
      window.dispatchEvent(new Event("online"));
    });
    expect(networkStatus.getSnapshot().online).toBe(true);
    quitar();
  });
});
