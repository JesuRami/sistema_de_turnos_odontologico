import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { createRetryQueue, MAX_ATTEMPTS, MAX_AGE_MS } from "./retryQueue";
import { RetryQueueIndicator } from "./RetryQueueIndicator";

function reloj(inicio = 1_000_000): { now: () => number; avanzar: (ms: number) => void } {
  let t = inicio;
  return { now: () => t, avanzar: (ms) => (t += ms) };
}

describe("cola de reintentos de recepción (C-14)", () => {
  it("reintenta hasta que la red vuelve y avisa al terminar", async () => {
    const r = reloj();
    const cola = createRetryQueue({ now: r.now, random: () => 0.5 });
    const run = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(0, "network_error"))
      .mockResolvedValueOnce({});
    const onDone = vi.fn();
    cola.enqueue({ id: "appt-1:present", label: "Asistencia · 10:00 · Sillón 1", run, onDone });

    await cola.flush();
    expect(run).not.toHaveBeenCalled(); // todavía no venció la primera espera
    r.avanzar(1000);
    await cola.flush();
    expect(cola.getSnapshot()[0]?.status).toBe("pending");
    await cola.flush(true);

    expect(run).toHaveBeenCalledTimes(2);
    expect(cola.getSnapshot()[0]).toMatchObject({ status: "done", attempts: 2 });
    expect(onDone).toHaveBeenCalledOnce();
  });

  it("un 409 invalid_transition al reintentar se toma como ya aplicado", async () => {
    const cola = createRetryQueue();
    cola.enqueue({
      id: "appt-1:confirmed",
      label: "Confirmado",
      run: () => Promise.reject(new ApiError(409, "invalid_transition"))
    });
    await cola.flush(true);
    expect(cola.getSnapshot()[0]?.status).toBe("done");
  });

  it("un error de negocio no se reintenta", async () => {
    const run = vi.fn().mockRejectedValue(new ApiError(409, "attendance_too_early"));
    const cola = createRetryQueue();
    cola.enqueue({ id: "x", label: "Presente", run });
    await cola.flush(true);
    await cola.flush(true);
    expect(run).toHaveBeenCalledOnce();
    expect(cola.getSnapshot()[0]).toMatchObject({ status: "failed", error: "attendance_too_early" });
  });

  it("abandona a los MAX_ATTEMPTS intentos o pasada la vida máxima", async () => {
    const r = reloj();
    const cola = createRetryQueue({ now: r.now });
    const run = vi.fn().mockRejectedValue(new ApiError(0, "network_error"));
    cola.enqueue({ id: "a", label: "A", run });
    for (let i = 0; i < MAX_ATTEMPTS + 2; i += 1) {
      await cola.flush(true);
    }
    expect(run).toHaveBeenCalledTimes(MAX_ATTEMPTS);
    expect(cola.getSnapshot()[0]?.status).toBe("failed");

    const vieja = createRetryQueue({ now: r.now });
    vieja.enqueue({ id: "b", label: "B", run });
    r.avanzar(MAX_AGE_MS + 1);
    await vieja.flush(true);
    expect(vieja.getSnapshot()[0]?.status).toBe("failed");
  });

  it("el mismo cambio encolado dos veces queda una sola vez (vale el último clic)", () => {
    const cola = createRetryQueue();
    cola.enqueue({ id: "appt-1:present", label: "Primero", run: () => Promise.resolve() });
    cola.enqueue({ id: "appt-1:present", label: "Segundo", run: () => Promise.resolve() });
    expect(cola.getSnapshot().map((c) => c.label)).toEqual(["Segundo"]);
  });

  it("el indicador muestra lo pendiente, permite reintentar ya y ocultar lo enviado", async () => {
    const user = userEvent.setup();
    const cola = createRetryQueue();
    const run = vi.fn().mockResolvedValue({});
    render(<RetryQueueIndicator queue={cola} />);
    expect(screen.queryByRole("region")).not.toBeInTheDocument();

    act(() => cola.enqueue({ id: "a", label: "Asistencia registrada: Presente · 10:00 · Sillón 1", run }));
    expect(screen.getByRole("region", { name: "Cambios pendientes de enviar" })).toHaveTextContent(
      "1 cambio pendiente de enviar. No cierres esta pestaña."
    );

    await user.click(screen.getByRole("button", { name: "Reintentar ahora" }));
    expect(await screen.findByText("· Enviado")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Quitar aviso/ }));
    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });
});
