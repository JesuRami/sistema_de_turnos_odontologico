import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { server } from "../test/server";
import { loggedSession, makeUser, renderWithProviders } from "../test/render";
import ChangePasswordPage from "./ChangePasswordPage";

function pantalla() {
  return (
    <Routes>
      <Route path="/cambiar-clave" element={<ChangePasswordPage />} />
      <Route path="/" element={<p>Agenda de prueba</p>} />
    </Routes>
  );
}

const PROVISORIO = makeUser("admin", { must_change_password: true });

async function completar(
  user: ReturnType<typeof import("@testing-library/user-event").default.setup>,
  nueva: string,
  confirmacion = nueva
) {
  await user.type(screen.getByLabelText("Contraseña actual"), "provisoria-ficticia");
  await user.type(screen.getByLabelText("Contraseña nueva"), nueva);
  await user.type(screen.getByLabelText("Repetir contraseña nueva"), confirmacion);
  await user.click(screen.getByRole("button", { name: "Cambiar contraseña" }));
}

describe("ChangePasswordPage", () => {
  it("cambia la clave, recarga el perfil y entra a la agenda", async () => {
    let enviado: unknown = null;
    server.use(
      http.post("/api/auth/change-password", async ({ request }) => {
        enviado = await request.json();
        return HttpResponse.json({ status: "ok" });
      }),
      http.get("/api/auth/me", () => HttpResponse.json({ ...PROVISORIO, must_change_password: false }))
    );
    const { user } = renderWithProviders(pantalla(), {
      route: "/cambiar-clave",
      session: await loggedSession(PROVISORIO)
    });

    await completar(user, "clave-nueva-ficticia-1");

    expect(await screen.findByText("Agenda de prueba")).toBeInTheDocument();
    expect(enviado).toEqual({
      current_password: "provisoria-ficticia",
      new_password: "clave-nueva-ficticia-1"
    });
  });

  it("no envía si la confirmación no coincide", async () => {
    const { user } = renderWithProviders(pantalla(), {
      route: "/cambiar-clave",
      session: await loggedSession(PROVISORIO)
    });

    await completar(user, "clave-nueva-ficticia-1", "otra-clave-ficticia-2");

    expect(screen.getByRole("alert")).toHaveTextContent("Las contraseñas no coinciden");
  });

  it("muestra el motivo cuando la API rechaza la clave nueva", async () => {
    server.use(
      http.post("/api/auth/change-password", () =>
        HttpResponse.json({ detail: [{ loc: ["body", "new_password"] }] }, { status: 422 })
      )
    );
    const { user } = renderWithProviders(pantalla(), {
      route: "/cambiar-clave",
      session: await loggedSession(PROVISORIO)
    });

    await completar(user, "corta-123456");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "La contraseña nueva debe tener entre 12 y 128 caracteres y ser distinta de la actual"
    );
    expect(screen.getByRole("button", { name: "Cambiar contraseña" })).toBeInTheDocument();
  });

  it("clave actual incorrecta", async () => {
    server.use(
      http.post("/api/auth/change-password", () =>
        HttpResponse.json({ detail: "invalid_credentials" }, { status: 401 })
      )
    );
    const { user } = renderWithProviders(pantalla(), {
      route: "/cambiar-clave",
      session: await loggedSession(PROVISORIO)
    });

    await completar(user, "clave-nueva-ficticia-1");

    expect(await screen.findByRole("alert")).toHaveTextContent("La contraseña actual no es correcta");
  });
});
