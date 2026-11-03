import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import App from "./App";
import { createSession } from "./shared/auth/session";
import { agendaHandlers } from "./test/fixtures";
import { anonymousSession, loggedSession, makeUser, renderWithProviders } from "./test/render";
import { server } from "./test/server";

describe("rutas protegidas", () => {
  it("sin sesión lleva al login y después vuelve a la ruta pedida", async () => {
    server.use(
      ...agendaHandlers(),
      http.post("/api/auth/login", () =>
        HttpResponse.json({
          access_token: "a",
          token_type: "bearer",
          expires_in: 900,
          user: makeUser("recepcion")
        })
      )
    );
    const { user } = renderWithProviders(<App />, {
      route: "/bloqueos",
      session: anonymousSession()
    });

    expect(await screen.findByRole("heading", { name: "Ingresar" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Email"), "recepcion.ficticia@example.com");
    await user.type(screen.getByLabelText("Contraseña"), "clave-ficticia-larga");
    await user.click(screen.getByRole("button", { name: "Ingresar" }));

    expect(await screen.findByRole("heading", { name: "Bloqueos" })).toBeInTheDocument();
  });

  it("al recargar recupera la sesión con la cookie y muestra la misma ruta", async () => {
    server.use(
      ...agendaHandlers(),
      http.post("/api/auth/refresh", () =>
        HttpResponse.json({ access_token: "b", token_type: "bearer", expires_in: 900 })
      ),
      http.get("/api/auth/me", () => HttpResponse.json(makeUser("admin")))
    );
    renderWithProviders(<App />, {
      route: "/politicas",
      session: createSession({ locks: null, channel: null })
    });

    expect(await screen.findByRole("heading", { name: "Políticas de la clínica" })).toBeInTheDocument();
  });

  it.each([
    ["recepcion", "/admin/profesionales"],
    ["odontologo", "/admin/sillones"],
    ["odontologo", "/politicas"],
    ["odontologo", "/pacientes/fusionar"]
  ] as const)("%s en %s ve acceso denegado", async (rol, ruta) => {
    server.use(...agendaHandlers());
    renderWithProviders(<App />, { route: ruta, session: await loggedSession(makeUser(rol)) });

    expect(await screen.findByText("No tenés permiso para esta sección")).toBeInTheDocument();
  });

  it("con clave provisoria cualquier ruta lleva al cambio de contraseña", async () => {
    server.use(...agendaHandlers());
    renderWithProviders(<App />, {
      route: "/",
      session: await loggedSession(makeUser("admin", { must_change_password: true }))
    });

    expect(await screen.findByRole("heading", { name: "Cambiar contraseña" })).toBeInTheDocument();
  });

  it("el menú muestra solo las secciones del rol", async () => {
    server.use(...agendaHandlers());
    renderWithProviders(<App />, {
      route: "/",
      session: await loggedSession(makeUser("odontologo"))
    });

    const nav = await screen.findByRole("navigation");
    expect(nav).toHaveTextContent("Agenda");
    expect(nav).toHaveTextContent("Bloqueos");
    expect(nav).not.toHaveTextContent("Profesionales");
    expect(nav).not.toHaveTextContent("Fusionar pacientes");
  });

  it("cerrar sesión vuelve al login", async () => {
    server.use(...agendaHandlers(), http.post("/api/auth/logout", () => new HttpResponse(null, { status: 204 })));
    const { user, session } = renderWithProviders(<App />, {
      route: "/",
      session: await loggedSession(makeUser("recepcion"))
    });

    await user.click(await screen.findByRole("button", { name: "Cerrar sesión" }));

    expect(await screen.findByRole("heading", { name: "Ingresar" })).toBeInTheDocument();
    await waitFor(() => expect(session.getAccess()).toBeNull());
  });
});
