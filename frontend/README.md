# Frontend — SPA del personal (C-06)

React 18 + TypeScript estricto (sin `any`, regla 5) + Vite 5 + Tailwind 3 +
TanStack Query. La SPA es la de la clínica (admin, recepción, odontólogo); las
ruta pública de reserva `/b/:slug` (C-07); la gestión por token `/g/:token` llega con C-08.

## Rutas

| Ruta | Roles |
|---|---|
| `/login`, `/cambiar-clave` | pública / sesión con clave provisoria |
| `/` agenda día (por sillón) y semana (por día) | admin, recepción, odontólogo (solo sus turnos, sin contacto) |
| `/bloqueos` | todos (alta); admin edita, retira y carga cierres |
| `/politicas` | admin (edita), recepción (solo lectura) |
| `/pacientes/fusionar` | admin, recepción |
| `/admin/profesionales`, `/admin/sillones`, `/admin/horarios` | admin |
| `/b/:slug` reserva pública (profesional → día → hora → datos) | anónima: sin sesión ni cookies, `QueryClient` propio |

La agenda de recepción se refresca sola cada 30 s (`refetchInterval`; con la pestaña oculta no
refresca): una reserva online aparece sin recargar. La reserva pública guarda todo en memoria
(nunca en `localStorage`/`sessionStorage`) y muestra las horas en la zona de la clínica.

Un rol sin permiso ve "No tenés permiso para esta sección". La UI oculta lo que
el rol no puede hacer, pero la autorización la sigue haciendo la API.

## Sesión (contrato de C-03)

- El access token vive **solo en memoria** (nunca `localStorage` ni
  `sessionStorage`, regla 10). Al recargar, la sesión se recupera con la cookie
  HttpOnly de refresh.
- **Renovación single-flight**: un único `POST /api/auth/refresh` en vuelo por
  pestaña y, entre pestañas, serializado con `navigator.locks`
  (`turnos-auth-refresh`). La pestaña que renueva difunde el access por
  `BroadcastChannel("turnos-auth")`. Un refresh rechazado cierra la sesión en
  todas las pestañas. Sin `navigator.locks` el single-flight queda por pestaña.
- El cliente reintenta una sola vez y solo ante `token_expired`,
  `token_invalid` o `invalid_session` (un `401 invalid_credentials` del cambio
  de contraseña no dispara renovación).

## Fechas

Todo se muestra y se carga en la zona de la clínica (`GET /api/clinic`), con
`Intl.DateTimeFormat` (`src/shared/time/zoned.ts`), también con cambio de horario.
Una hora inexistente por el salto de horario no se envía.

## Scripts

| Script | Qué hace |
|---|---|
| `npm run dev` | Vite en `:5173` con proxy `/api` → `API_PROXY_TARGET` (default `http://localhost:8000`) |
| `npm run typecheck` | `tsc --noEmit` estricto |
| `npm run test` | Vitest + Testing Library + MSW (jsdom, navegador en `TZ=UTC`) |
| `npm run e2e` | Playwright contra el stack real (ver abajo) |

## E2E

Requiere la API levantada (por defecto en `http://localhost:8000`) sobre una
base migrada con el seed de C-02. Playwright levanta Vite solo. Credenciales
solo por entorno (regla 6), todas sintéticas:

| Variable | Uso |
|---|---|
| `E2E_ADMIN_EMAIL` | email del admin del seed (`SEED_ADMIN_EMAIL`) |
| `E2E_ADMIN_PASSWORD` | su clave provisoria (`SEED_ADMIN_PASSWORD`) |
| `E2E_PASSWORD` | clave definitiva que el E2E fija para el admin y la recepcionista |
| `E2E_API` / `E2E_BASE_URL` | opcionales: API y URL de la SPA (usar `http://127.0.0.1:8000` en Windows: `localhost` resuelve a IPv6 y el proxy de Vite se cuelga) |
| `E2E_CLINIC_SLUG` | opcional: slug de la clínica con reserva habilitada (default `clinica-demo`) |

La clínica del seed debe tener la reserva pública habilitada: sembrarla con `SEED_BOOKING_DEMO=true`
y, en la API de pruebas, subir `PUBLIC_BOOKING_IP_RATE_LIMIT` (el default de 10 reservas/h/IP se agota
con corridas repetidas) y `BOOKING_RATE_LIMIT` (tope global en memoria).

El setup global crea por API recursos, paciente y una recepcionista propios de la
corrida (sufijo único) y 500 turnos en la semana siguiente. Specs:

- `e2e/agenda.spec.ts`: primer ingreso con cambio de clave → turno → `409` con
  alternativo → presente.
- `e2e/booking.spec.ts` (C-07): reserva en 4 pasos a 360×740 sin scroll horizontal y con botones ≥ 44 px,
  la agenda de recepción muestra la reserva pendiente en ≤ 30 s sin recargar y la carrera por el mismo
  hueco muestra "Ese horario se acaba de ocupar" con alternativos.
- `e2e/agenda-perf.spec.ts`: semana con 500 turnos visible en < 2 s (US-010 CA-3).

La API de pruebas debe tener límites de login holgados (`AUTH_*_RATE_LIMIT`).
Playwright en CI queda para C-14; en CI corre `npm run test`.
