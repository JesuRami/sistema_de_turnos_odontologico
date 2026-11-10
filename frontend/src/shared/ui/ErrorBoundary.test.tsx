import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ErrorBoundary } from "./ErrorBoundary";

function Explota(): JSX.Element {
  throw new Error("Ana Prueba +5491155550000");
}

describe("ErrorBoundary (C-14)", () => {
  it("muestra un aviso genérico sin el mensaje del error y ofrece recargar", async () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    const recargar = vi.fn();
    const user = userEvent.setup();
    render(
      <ErrorBoundary onReload={recargar}>
        <Explota />
      </ErrorBoundary>
    );

    const alerta = screen.getByRole("alert");
    expect(alerta).toHaveTextContent("Algo salió mal");
    expect(alerta).not.toHaveTextContent("5491155550000");
    await user.click(screen.getByRole("button", { name: "Recargar" }));
    expect(recargar).toHaveBeenCalledOnce();
  });

  it("sin error renderiza a los hijos", () => {
    render(
      <ErrorBoundary>
        <p>contenido</p>
      </ErrorBoundary>
    );
    expect(screen.getByText("contenido")).toBeInTheDocument();
  });
});
