import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { server } from "../test/server";
import { anonymousSession, makeUser, renderWithProviders } from "../test/render";
import LoginPage from "./LoginPage";

function pantalla() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={<p>Agenda de prueba</p>} />
      <Route path="/bloqueos" element={<p>Bloqueos de prueba</p>} />
      <Route path="/cambiar-clave" element={<p>Cambio de clave de prueba</p>} />
    </Routes>
  );
}

async function ingresar(
  user: ReturnType<typeof import("@testing-library/user-event").default.setup>
) {
  await user.type(screen.getByLabelText("Email"), "recepcion.ficticia@example.com");
  await user.type(screen.getByLabelText("Contraseña"), "clave-ficticia-larga");
  await user.click(screen.getByRole("button", { name: "Ingresar" }));
}

describe("LoginPage", () => {
  it("con credenciales válidas lleva a la agenda", async () => {
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json({
          access_token: "a",
          token_type: "bearer",
          expires_in: 900,
          user: makeUser("recepcion")
        })
      )
    );
    const { user } = renderWithProviders(pantalla(), {
      route: "/login",
      session: anonymousSession()
    });

    await ingresar(user);

    expect(await screen.findByText("Agenda de prueba")).toBeInTheDocument();
  });

  it("vuelve a la ruta que se pidió antes del login", async () => {
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json({
          access_token: "a",
          token_type: "bearer",
          expires_in: 900,
          user: makeUser("recepcion")
        })
      )
    );
    const { user } = renderWithProviders(pantalla(), {
      route: "/login?next=%2Fbloqueos",
      session: anonymousSession()
    });

    await ingresar(user);

    expect(await screen.findByText("Bloqueos de prueba")).toBeInTheDocument();
  });

  it("credenciales inválidas muestran un mensaje genérico", async () => {
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json({ detail: "invalid_credentials" }, { status: 401 })
      )
    );
    const { user } = renderWithProviders(pantalla(), {
      route: "/login",
      session: anonymousSession()
    });

    await ingresar(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("Email o contraseña incorrectos");
  });

  it("ante 429 informa cuándo reintentar y deshabilita el envío", async () => {
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json(
          { detail: "rate_limited" },
          { status: 429, headers: { "Retry-After": "30" } }
        )
      )
    );
    const { user } = renderWithProviders(pantalla(), {
      route: "/login",
      session: anonymousSession()
    });

    await ingresar(user);

    expect(await screen.findByRole("alert")).toHaveTextContent("reintentar en 30 segundos");
    expect(screen.getByRole("button", { name: "Ingresar" })).toBeDisabled();
  });

  it("con clave provisoria lleva al cambio de contraseña", async () => {
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json({
          access_token: "a",
          token_type: "bearer",
          expires_in: 900,
          user: makeUser("admin", { must_change_password: true })
        })
      )
    );
    const { user } = renderWithProviders(pantalla(), {
      route: "/login",
      session: anonymousSession()
    });

    await ingresar(user);

    expect(await screen.findByText("Cambio de clave de prueba")).toBeInTheDocument();
  });
});
