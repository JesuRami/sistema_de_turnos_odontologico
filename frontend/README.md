# Frontend — SPA del personal (C-06)

React 18 + TypeScript estricto (sin `any`, regla 5) + Vite 5 + Tailwind 3 +
TanStack Query. La SPA es la de la clínica (admin, recepción, odontólogo); las
rutas públicas del paciente (`/b/:slug`, `/g/:token`) llegan con C-07/C-08.

## Rutas

| Ruta | Roles |
|---|---|
| `/login`, `/cambiar-clave` | pública / sesión con clave provisoria |
| `/` agenda día (por sillón) y semana (por día) | admin, recepción, odontólogo (solo sus turnos, sin contacto) |
| `/bloqueos` | todos (alta); admin edita, retira y carga cierres |
| `/politicas` | admin (edita), recepción (solo lectura) |
| `/pacientes/fusionar` | admin, recepción |
| `/admin/profesionales`, `/admin/sillones`, `/admin/horarios` | admin |

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
| `E2E_API` / `E2E_BASE_URL` | opcionales: API y URL de la SPA |

El setup global crea por API recursos, paciente y una recepcionista propios de la
corrida (sufijo único) y 500 turnos en la semana siguiente. Specs:

- `e2e/agenda.spec.ts`: primer ingreso con cambio de clave → turno → `409` con
  alternativo → presente.
- `e2e/agenda-perf.spec.ts`: semana con 500 turnos visible en < 2 s (US-010 CA-3).

La API de pruebas debe tener límites de login holgados (`AUTH_*_RATE_LIMIT`).
Playwright en CI queda para C-14; en CI corre `npm run test`.
