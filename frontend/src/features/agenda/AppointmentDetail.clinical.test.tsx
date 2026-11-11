/** C-15: el enlace a la historia clínica solo aparece para odontólogo y admin (recepción no). */
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import type { UserRole } from "../../shared/api/types";
import { appointment, chair, professional, rule, timeline, TZ } from "../../test/fixtures";
import { loggedSession, makeUser, renderWithProviders } from "../../test/render";
import { server } from "../../test/server";
import AppointmentDetail from "./AppointmentDetail";

async function abrir(role: UserRole) {
  const turno = appointment();
  renderWithProviders(
    <AppointmentDetail
      appointment={turno}
      context={{ tz: TZ, role, professionals: [professional()], chairs: [chair()], schedules: [rule()] }}
      onClose={() => undefined}
      onReschedule={() => undefined}
      onDone={() => undefined}
    />,
    { session: await loggedSession(makeUser(role)) }
  );
  return turno;
}

describe("AppointmentDetail · historia clínica", () => {
  beforeEach(() => {
    server.use(http.get("/api/appointments/:id/reminders", () => HttpResponse.json(timeline([]))));
  });

  it.each(["odontologo", "admin"] as const)("%s ve el enlace a la historia clínica", async (role) => {
    const turno = await abrir(role);
    const link = await screen.findByRole("link", { name: /Historia clínica/ });
    expect(link).toHaveAttribute("href", `/pacientes/${turno.patient.id}/historia-clinica`);
  });

  it("recepción no ve el enlace", async () => {
    await abrir("recepcion");
    await screen.findAllByText(/Cancelar|Confirmar|Reprogramar/);
    expect(screen.queryByRole("link", { name: /Historia clínica/ })).not.toBeInTheDocument();
  });
});
