/** Render de tests con los providers de la app: Query, sesión y router en memoria. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import type { UserProfile, UserRole } from "../shared/api/types";
import { AuthProvider } from "../shared/auth/AuthProvider";
import { createSession, type Session } from "../shared/auth/session";
import { NowProvider, type Clock } from "../shared/time/now";
import { server } from "./server";

export interface Rendered extends RenderResult {
  session: Session;
  user: ReturnType<typeof userEvent.setup>;
  queryClient: QueryClient;
}

export function makeUser(role: UserRole, overrides: Partial<UserProfile> = {}): UserProfile {
  return {
    id: `user-${role}`,
    email: `${role}.ficticio@example.com`,
    role,
    clinic_id: "clinic-1",
    professional_id: role === "odontologo" ? "prof-1" : null,
    must_change_password: false,
    last_login_at: null,
    ...overrides
  };
}

/** Sesión ya autenticada (login contra MSW), sin locks ni canal entre pestañas. */
export async function loggedSession(user: UserProfile): Promise<Session> {
  server.use(
    http.post("/api/auth/login", () =>
      HttpResponse.json({ access_token: "acceso-test", token_type: "bearer", expires_in: 900, user })
    )
  );
  const session = createSession({ locks: null, channel: null });
  await session.login(user.email, "clave-ficticia-larga");
  return session;
}

export function anonymousSession(): Session {
  server.use(
    http.post("/api/auth/refresh", () =>
      HttpResponse.json({ detail: "invalid_refresh" }, { status: 401 })
    )
  );
  return createSession({ locks: null, channel: null });
}

export function renderWithProviders(
  ui: ReactElement,
  options: { route?: string; session: Session; now?: Clock }
): Rendered {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } }
  });
  const user = userEvent.setup();
  const resultado = render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider session={options.session}>
        <NowProvider clock={options.now ?? (() => new Date())}>
          <MemoryRouter initialEntries={[options.route ?? "/"]}>{ui}</MemoryRouter>
        </NowProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
  return { ...resultado, session: options.session, user, queryClient };
}
