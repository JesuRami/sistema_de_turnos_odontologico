# Proposal — C-06 `agenda-spa-recepcion`

## Why

C-03 a C-05 dejaron toda la agenda en la API, pero el frontend sigue siendo el
stub de C-01: sin login, sin cliente autenticado y sin pantallas. Recepción no
puede operar el día (Flujo 4) ni el admin configurar la clínica sin llamar a la
API a mano. C-06 entrega la SPA del personal y cierra el último hueco de datos
del Flujo 4: los pacientes duplicados se fusionan de forma asistida, nunca se
borran.

## What Changes

- **Sesión del personal en la SPA**: login, cambio de contraseña obligatorio,
  logout y rutas protegidas por rol. Access token solo en memoria (regla 10);
  refresh por cookie HttpOnly con **single-flight entre pestañas** (contrato de
  C-03: un refresh ya rotado revoca la familia). Ante `401` en el refresh, la
  sesión local se cierra y se vuelve al login.
- **Agenda del día y de la semana** (US-010): grilla propia por sillón (día) y
  por día (semana), en la zona horaria de la clínica. Filtros por profesional,
  sillón y estado; color por profesional; distintivo por estado, sobreturno y
  bloqueo; pendientes sin confirmar que empiezan en menos de 24 h destacados.
  Objetivo: una semana con 500 turnos visible en < 2 s (US-010 CA-3).
- **Operación de turnos** (US-011 a US-013, Flujo 4): crear turno buscando al
  paciente o con alta rápida; ante `409 slot_taken`, elegir un alternativo o
  marcar sobreturno con motivo (solo admin y recepción); reprogramar; cancelar
  con motivo del catálogo; confirmar; marcar presente, ausente o no-show. La
  UI muestra el error de dominio de la API sin inventar reglas propias: la API
  sigue siendo la única autoridad.
- **Vista del odontólogo**: solo sus turnos, sin teléfono ni email del
  paciente, y solo las acciones de asistencia (la API ya lo impone; la UI no
  ofrece lo que la API rechazaría).
- **Pantallas de administración** (US-001 a US-004): profesionales, sillones,
  plantilla semanal, bloqueos (incluido el cierre de clínica) y políticas.
  Crear o editar un bloqueo que pisa turnos muestra los afectados y permite
  cancelarlos en la misma operación (RN-BL-02).
- **Fusión asistida de pacientes duplicados** (Flujo 4, caso de error):
  `GET /api/patients/{id}` y `POST /api/patients/{id}/merge`. El paciente
  duplicado queda archivado y apuntando al que se conserva; sus turnos pasan
  al conservado con evento de auditoría por turno, y la fusión queda en un
  registro append-only. Solo admin y recepción.
- **Perfil de la clínica para el personal**: `GET /api/clinic` devuelve nombre
  y zona horaria a todos los roles (hoy la zona no la expone ningún endpoint y
  la grilla la necesita).
- **Tests de frontend**: Vitest + Testing Library con mock de red (MSW) para
  lógica y componentes; Playwright E2E contra el stack real para el circuito
  login → crear turno → presente.
- **Migración `c06_patient_merge`** (una sola revisión, regla 3).

## Out of scope (explícito)

- **ABM de usuarios del personal** (la API de C-03 existe): se registra en
  CHANGES como diferido; hoy el alta de personal es por API o seed.
- **Reenvío de recordatorios y timeline de entregas** (Flujo 4 paso 3): C-09 y
  C-10. La agenda deja el lugar, sin botón activo.
- **Lista de espera y oferta manual** (Flujo 4 paso 5): C-12.
- **Reporte de pendientes sin confirmar** (Flujo 4 paso 6): C-13. C-06 solo
  los destaca en la grilla.
- **Arrastrar y soltar** para reprogramar: la reprogramación es por
  formulario; el drag & drop queda como mejora posterior.
- **Agenda imprimible u offline** (SU-06): C-14.
- Booking público (C-07) y gestión por token (C-08).

## Capabilities

### New Capabilities

- `web/staff-session`: sesión del personal en la SPA: login, cambio de
  contraseña obligatorio, renovación single-flight entre pestañas, logout y
  rutas por rol.
- `web/agenda-board`: agenda día/semana del personal con filtros, distintivos y
  operación de turnos (crear, alternativos, sobreturno, reprogramar, cancelar,
  confirmar, asistencia), vista restringida del odontólogo y fusión asistida de
  pacientes.
- `web/agenda-admin`: pantallas de configuración de la clínica: profesionales,
  sillones, plantilla semanal, bloqueos con resolución de turnos afectados y
  políticas.

### Modified Capabilities

- `core/patients`: se agregan la consulta de un paciente por id y la fusión
  asistida de duplicados con auditoría.
- `core/clinic-resources`: se agrega la consulta del perfil de la clínica
  (nombre y zona horaria) por todo el personal.

## Impact

- Frontend: `src/shared` (cliente API tipado con auth, sesión, UI kit, fechas
  en zona de la clínica), `src/features/agenda`, `src/features/admin`,
  `src/features/patients`, rutas protegidas. Dependencias nuevas:
  `@tanstack/react-query`; dev: `vitest`, `@testing-library/react`,
  `@testing-library/user-event`, `jsdom`, `msw`, `@playwright/test`.
  TypeScript estricto sin `any` (regla 5).
- Backend: `app/modules/patients` (detalle y fusión), `app/modules/clinic`
  (perfil). Schemas con `extra='forbid'` (regla 2).
- DB: `patient.merged_into_patient_id` (FK compuesta `NOT VALID` → `VALIDATE`,
  regla 11) y tabla append-only `patient_merge` con trigger (regla 7: nunca
  borrado).
- CI: el job frontend suma `vitest run`; Playwright corre contra el stack de
  Docker Compose.
- Governance: **ALTO** (MEDIO en CHANGES, sube porque la fusión reasigna
  turnos y toca datos de pacientes).
