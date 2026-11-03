# Design — C-06 `agenda-spa-recepcion`

## Context

El frontend es el stub de C-01: React 18 + TS estricto + Vite 5 + Tailwind 3 +
react-router 6, un `fetch` sin auth y páginas vacías; no hay runner de tests.
El backend ya expone auth (C-03), recursos, plantilla, bloqueos y políticas
(C-04), turnos y pacientes (C-05). Falta en la API: la zona horaria de la
clínica para todos los roles, el detalle de un paciente y la fusión.

Contratos heredados que la SPA debe respetar:
- Refresh con rotación estricta: un refresh ya rotado responde `401
  refresh_reuse` y revoca la familia (README C-03 §single-flight).
- `refresh` y `logout` exigen `Origin` permitido (`CORS_ORIGINS`).
- La API es la autoridad de reglas y de alcance: la UI oculta lo que el rol no
  puede hacer, pero nunca decide sola (KB 08 §Autorización).

Decisiones del usuario (2026-11-03): fusión incluida en C-06 con backend
mínimo; Vitest + Testing Library + MSW y Playwright; TanStack Query y grilla
propia; ABM de usuarios fuera de alcance.

## Goals / Non-Goals

**Goals:**
- Recepción opera el día completo del Flujo 4 (pasos 1, 2, 4 y 5 en su parte de
  turnos) sin tocar la API a mano.
- Cero violaciones del contrato de refresh aunque haya varias pestañas.
- Fechas siempre en la zona de la clínica, también con cambio de horario.
- Fusión de duplicados atómica, auditada y sin borrado.

**Non-Goals:**
- Drag & drop, impresión u offline, ABM de usuarios, recordatorios, lista de
  espera, reportes (ver proposal).
- Generar tipos desde OpenAPI: los tipos de borde se escriben a mano (D2).

## Decisions

### D1. Sesión: access en memoria + single-flight por origen

- `shared/auth/session.ts` guarda el access en una variable de módulo (nunca en
  `localStorage`/`sessionStorage`, regla 10) y expone `getAccess()`,
  `setSession()`, `clearSession()` y suscripción para React (`AuthProvider`).
- **Single-flight**: `refreshAccess()` comparte una promesa por pestaña y
  además se serializa entre pestañas con `navigator.locks.request(
  "turnos-auth-refresh")`. Al terminar, la pestaña difunde el access nuevo por
  `BroadcastChannel("turnos-auth")`. Una pestaña que esperaba el lock y recibió
  un access emitido **después** de iniciar su espera lo usa y no refresca.
  Así nunca hay dos refresh en vuelo con la misma cookie.
- Fallback sin `navigator.locks` (navegadores viejos): single-flight solo por
  pestaña, documentado como riesgo (el peor caso es volver al login).
- El cliente reintenta una sola vez tras refrescar; si el refresh responde
  `401`, difunde `logout` y todas las pestañas limpian sesión y cachés.
- Arranque: sin access en memoria, la SPA intenta `refresh` (bajo el mismo
  lock) antes de decidir si muestra el login.
- `must_change_password` del perfil de `/auth/login` o `/auth/me` redirige a
  `/cambiar-clave`; el guard bloquea el resto.

Alternativa descartada: guardar el access en `sessionStorage` para compartirlo
entre pestañas — viola la regla 10.

### D2. Cliente API tipado

`shared/api/client.ts`: `apiFetch<T>(path, {method, body, query})` con
`credentials: "include"` (la cookie de refresh es HttpOnly y de mismo origen vía
proxy), `Authorization: Bearer` desde memoria y errores como `ApiError {status,
detail, extra}` (campos extra del cuerpo: `conflicts`, `alternatives`,
`blocks`, `appointments`, `patient_id`). Los tipos de cada borde viven en
`shared/api/types.ts`, escritos a mano a partir de los schemas Pydantic, sin
`any` (regla 5): las respuestas se tipan como `unknown` y se estrechan con
guards mínimos en el borde.

Alternativa descartada: `openapi-typescript`. Exige levantar la API para
regenerar y suma una dependencia; con ~25 tipos el costo no se justifica en
v1. Queda anotado si el contrato crece.

### D3. Datos con TanStack Query

- Claves: `["appointments", from, to, filtros]`, `["blocks", from, to]`,
  `["professionals"]`, `["chairs"]`, `["schedules"]`, `["policies"]`,
  `["clinic"]`, `["patients", q]`.
- El rango de agenda se pide completo siguiendo `next_cursor` (turnos con
  `limit=500`, bloqueos con `limit=200`) hasta agotar páginas.
- Mutaciones de turnos y bloqueos invalidan `appointments` y `blocks` del
  rango; no hay updates optimistas (la API decide; D7).
- `staleTime` 30 s y refetch al volver el foco: la agenda la miran varias
  personas a la vez.

### D4. Fechas en la zona de la clínica sin librería

`shared/time/zoned.ts` sobre `Intl.DateTimeFormat` con `timeZone` de
`GET /api/clinic`:
- `toZonedParts(instant, tz)` → año, mes, día, hora, minuto, día de semana.
- `fromZonedWallTime(fecha, hora, tz)` → instante, resolviendo el offset por
  iteración (dos pasadas) y rechazando horas inexistentes por cambio de
  horario.
- `startOfZonedDay/Week` para los rangos `from/to` de la API.
Los tests cubren `America/Argentina/Buenos_Aires` y una zona con DST
(`Europe/Madrid`) con el navegador en `UTC` (`TZ=UTC` en Vitest).

### D5. Grilla de agenda propia

- Vista día: columnas = sillones activos (filtrables); filas = intervalos de
  15 min entre el mínimo inicio y el máximo fin de las reglas del día (por
  defecto 08:00–20:00). Turnos y bloqueos se posicionan con CSS grid por
  minutos desde el inicio visible.
- Vista semana: columnas = días; dentro de cada día los turnos que se solapan
  (sillones distintos, sobreturnos) se reparten en carriles.
- Color por profesional (`professional.color`, o uno derivado estable del id si
  es nulo) + texto de estado, para no depender solo del color (accesibilidad).
- Rendimiento (US-010 CA-3): cálculo de layout memoizado por rango y filtros,
  componentes de turno memoizados, sin librería de virtualización (500 nodos
  es manejable). Se mide en E2E (D10).

### D6. Rutas y guards

| Ruta | Roles |
|---|---|
| `/login`, `/cambiar-clave` | pública / sesión con clave provisoria |
| `/` (agenda día/semana) | admin, recepción, odontólogo |
| `/bloqueos` | admin, recepción, odontólogo (alta; editar y cierres solo admin) |
| `/politicas` | admin (edita), recepción (solo lectura) |
| `/admin/profesionales`, `/admin/sillones`, `/admin/horarios` | admin |
| `/pacientes/fusionar` | admin, recepción |

`RequireSession` y `RequireRole` envuelven las rutas; un rol sin permiso ve
"No tenés permiso para esta sección". Las acciones por turno salen de una
tabla `allowedActions(rol, turno, ahora)` que replica las guardas de la API
solo para **ocultar** botones; la API sigue rechazando lo indebido.

### D7. Operación de turnos

- Formulario de turno (crear y reprogramar) con búsqueda de pacientes
  (debounce 300 ms, mínimo 3 caracteres) y alta rápida inline.
- `409 slot_taken`: panel con los alternativos (horario en zona de la clínica)
  y, para admin/recepción, "Crear como sobreturno" con motivo obligatorio. Se
  reintenta con el mismo body cambiando `starts_at` o `is_overbooking`.
- Cancelación: motivo del catálogo obligatorio + nota ≤ 500.
- Asistencia: botones según D6; texto de ayuda "Ausente: avisó. No-show: no
  avisó".
- Sin actualización optimista: tras cada mutación se invalida el rango y la
  grilla muestra lo que devuelve la API (si falla, el turno queda como estaba).

### D8. Catálogo de errores

`shared/api/errors.ts` mapea cada `detail` conocido (C-03 a C-06) a un mensaje
en español rioplatense; `detail` desconocido → "No se pudo completar la
operación". Los mensajes nunca interpolan datos de pacientes (regla 13).

### D9. Fusión de pacientes (backend)

- Migración `c06_patient_merge`:
  - `patient.merged_into_patient_id uuid NULL` (`ADD COLUMN` metadata-only).
  - FK compuesta `(merged_into_patient_id, clinic_id) → patient(id, clinic_id)`
    (usa el UNIQUE `uq_patient_id_clinic_id` de C-05) con `NOT VALID` →
    `VALIDATE` (regla 11).
  - CHECKs `NOT VALID` → `VALIDATE`: `merged_into_patient_id <> id` y
    `merged_into_patient_id IS NULL OR archived_at IS NOT NULL`.
  - Tabla nueva `patient_merge` (`id, clinic_id, source_patient_id,
    target_patient_id, actor_user_id, appointment_ids jsonb, filled_fields
    jsonb, created_at clock_timestamp()`) con FKs compuestas y trigger
    append-only `BEFORE UPDATE OR DELETE` (igual que las otras auditorías).
- `POST /api/patients/{id}/merge` body `{into_patient_id}` (`extra='forbid'`),
  admin y recepción:
  1. `SELECT … FOR UPDATE` sobre ambos pacientes, ordenados por id.
  2. Validar: distintos, misma clínica, ninguno archivado → si no, `422
     invalid_merge` (sin revelar existencia).
  3. Completar en el conservado los campos de contacto nulos (`phone_e164`,
     `email`, `dni`) con los del duplicado; `whatsapp_opt_in` no se hereda (el
     consentimiento es del contacto que lo dio).
  4. Reasignar los turnos del duplicado (todos los estados) con un evento
     `updated` por turno: `{patient_id: [anterior, nuevo], reason:
     "patient_merge", merge_id}`.
  5. Archivar el duplicado (`archived_at`, `merged_into_patient_id`) y
     escribir `patient_merge`; todo en una transacción.
- **Carrera con el alta de turnos**: `AppointmentsService._assert_patient`
  pasa a leer el paciente con `FOR SHARE`; la fusión toma `FOR UPDATE`, así un
  turno nuevo no puede quedar colgado del duplicado.
- `GET /api/patients/{id}` (admin, recepción) devuelve el paciente con
  `archived_at`, `merged_into_patient_id` y `appointments_count` para la
  pantalla de fusión.

Alternativa descartada: mover también la lista de espera y los jobs; no existen
todavía. Contrato: C-09 y C-12 deben reasignar o cancelar sus filas en la misma
transacción de la fusión.

### D10. Perfil de clínica

`GET /api/clinic` (todo el personal) → `{id, name, timezone}` desde la clínica
del principal. Sin políticas (esas siguen en `/api/clinic/policies`).

### D11. Tests

- **Vitest + Testing Library + MSW** (jsdom, `TZ=UTC`): `session` (single-flight
  en pestaña y con lock/BroadcastChannel simulados), `client` (reintento único,
  logout ante `401` del refresh), `zoned` (DST), layout de grilla, guards,
  formularios de turno (409 con alternativos y sobreturno), bloqueo con
  afectados, fusión, catálogo de errores. Cada test se escribe y se ve fallar
  antes del código (TDD).
- **pytest** (Postgres real, regla 9): fusión, `GET /api/patients/{id}`,
  `GET /api/clinic`, migración y drift, aislamiento cross-tenant, carrera
  fusión vs. alta de turno (dos sesiones), y la consulta de una semana con
  500 turnos.
- **Playwright** contra Docker Compose con seed sintético: login con cambio de
  clave → crear turno (incluido 409 con alternativo) → marcar presente; y la
  semana con 500 turnos visible en < 2 s. Datos solo sintéticos (regla 13).
- CI: el job frontend suma `npm run test` (Vitest). Playwright se corre en el
  gate local con el stack levantado; integrarlo a CI queda para C-14.

## Risks / Trade-offs

- [`navigator.locks` ausente] → single-flight solo por pestaña; el peor caso es
  un reuso que cierra la sesión y pide login. Soportado en navegadores
  actuales.
- [Tipos escritos a mano divergen del backend] → tests MSW con cuerpos tomados
  de los schemas y E2E contra la API real.
- [Grilla propia] → más código que una librería; se acota a día/semana sin
  drag & drop.
- [Fusión irreversible] → confirmación explícita en la UI y auditoría completa
  para reconstruir a mano si hiciera falta.
- [`FOR SHARE` en el alta de turnos] → lock liviano compatible entre altas
  concurrentes del mismo paciente; solo espera durante una fusión.

## Migration Plan

`c06_patient_merge` (revises `c05_appointments_core`): columna →
FK/CHECKs `NOT VALID` → `VALIDATE` → tabla `patient_merge` + función y trigger.
Downgrade inverso: elimina `patient_merge` (se pierde la auditoría de fusiones,
advertido en README) y la columna; los pacientes fusionados quedan archivados
pero sin el puntero. CI ya corre `upgrade → downgrade -1 → upgrade`.

## Open Questions

- Ninguna bloqueante. Se asume que el perfil del odontólogo no necesita ver
  bloqueos ajenos (la API de C-04 ya los acota a los suyos).
