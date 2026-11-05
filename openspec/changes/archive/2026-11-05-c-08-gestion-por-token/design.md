# Design — C-08 `gestion-por-token`

Motivación y alcance: `proposal.md`. Comportamiento exigido: `specs/`.

## Context

- C-07 dejó: `appointment.manage_token_hash bytea` (SHA-256 de 32 bytes), índice
  único parcial `uq_appointment_manage_token_hash`, CHECKs
  `manage_token_hash_length` y `online_has_manage_token`; el token se emite como
  `secrets.token_urlsafe(32)` y la respuesta 201 devuelve
  `manage_url = {FRONTEND_PUBLIC_URL}/g/{token}`.
- La SPA ya tiene la ruta `/g/:token` apuntando a `pages/ManagePage.tsx`, que hoy
  es un placeholder, y `features/manage/index.ts` vacío.
- C-05 dejó `AppointmentsService` como único punto de escritura de `appointment`,
  con `apply_transition` (roles vacíos ⇒ no exige rol de personal), la máquina de
  estados `ALLOWED`, el `EXCLUDE USING gist` como barrera final y
  `record_event` (append-only, `actor_type` admite `patient_token`).
  `_reschedule` valida y escribe de forma atómica pero **no** es reutilizable:
  vive detrás de `update()`, que hace `commit` y solo admite un intento.
- C-13 (`reports`) ya lee `appointment_event`, agrupa cancelaciones por
  `payload.reason` sobre los 5 valores de `CancellationReason` y mapea lo
  desconocido a `otro`. **No se toca.**
- `clinic` tiene `cancellation_window_hours` (default 24) pero **no** tiene
  teléfono de contacto, y RN-ON-04/RN-CX-01 exigen derivar a la clínica.
- `BookingPublicService.offerable()` es la única definición de "hueco
  ofrecible" y `public_slots` es puro; se reutiliza tal cual.
- C-09 (recordatorios) todavía no existe: no hay `reminder_job`.
- Cabeza de Alembic: `c07_booking_public`.

## Goals / Non-Goals

**Goals:**
- Un único núcleo de transiciones (`AppointmentsService`) compartido por el link,
  la recepción y, después, el webhook de C-10.
- Que el token no pueda usarse para enumerar turnos, pacientes ni agendas.
- Idempotencia por estado (no por clave de idempotencia almacenada): reintentar
  es seguro sin tabla nueva.
- Cero cambios en `appointment`: el TTL se deriva y la idempotencia es por
  estado.

**Non-Goals:**
- Programar/enviar recordatorios (C-09/C-10), webhook (C-10), reportes (C-13),
  rotación obligatoria del token, reprogramación a otro profesional.

## Decisions

### D1. Superficie: tres endpoints, token en el path

| Método | Ruta | Uso |
|---|---|---|
| `GET` | `/api/manage/{token}` | vista de gestión |
| `GET` | `/api/manage/{token}/availability?from&to` | huecos para reprogramar |
| `PATCH` | `/api/manage/{token}` | `confirm` \| `cancel` \| `reschedule` |

Router `manage` fino (rate-limit, cabeceras, traducción HTTP) → `ManageService`.
Sin `Principal` ni cookie de sesión: la clínica y el turno se resuelven **solo**
por el token, y todo se filtra por el `clinic_id` del turno (regla 4).

`PATCH` con cuerpo discriminado (`action` como discriminador, `extra='forbid'` en
cada variante, regla 2):

```jsonc
{"action": "confirm"}
{"action": "cancel", "reason": "viaje", "note": "opcional ≤ 200"}
{"action": "reschedule", "starts_at": "2026-11-12T14:30:00-03:00"}
```

Se elige un único endpoint sobre tres rutas porque el recurso es el mismo turno,
la idempotencia es por estado y el frontend necesita un solo camino de error.

### D2. Transporte e higiene del token

- **Path, no query string** (y no header): C-07 ya emitió links
  `/g/{token}` y CHANGES.md fija `PATCH /api/manage/:token`; un header
  obligaría a cambiar el contrato del link y a un preflight CORS. El query
  string queda descartado explícitamente: se filtra por `Referer`, por logs de
  proxies y por historiales.
- **Nunca se compara el token en memoria**: se calcula `sha256(token)` y se
  busca por igualdad contra el índice único (32 bytes). Un atacante no puede
  sacar información temporal útil sobre un preimage de 256 bits, así que no hace
  falta `compare_digest`; se documenta para que nadie "optimice" a comparar el
  token en claro.
- **Formato** `^[A-Za-z0-9_-]{43}$`: un token malformado se rechaza sin tocar la
  base (404 uniforme).
- **Redacción de logs**: la aplicación no loguea ni el path ni el token (ningún
  `logger` del módulo recibe la request); el test de fuga revisa `caplog` y el
  cuerpo del error. `backend/README.md` documenta que el access log de
  uvicorn/nginx debe redactar `/g/` y `/api/manage/` (formato de log propio), y
  el healthcheck del despliegue no toca esas rutas.
- **Cabeceras**: `Cache-Control: no-store` y `Referrer-Policy: no-referrer` en
  las tres respuestas; la página agrega `<meta name="robots" content="noindex">`.
- Ni `localStorage` ni `sessionStorage` ni cookies en el frontend.

### D3. Ciclo de vida y TTL

- `expires_at = ends_at + MANAGE_TOKEN_TTL_H` (setting existente, default 72 h),
  calculado en el servidor en cada request. `ends_at` (no `starts_at`) porque
  RN-ON-04 dice "72 h post-turno": el paciente puede consultar el resultado
  después de atenderse.
- Ventana de validez `[created_at, expires_at]`. No se agrega columna de
  expiración: derivarla evita backfill, drift y una fuente de verdad duplicada, y
  cambiar el setting aplica retroactivamente a links ya emitidos (deseable en
  piloto, documentado).
- **Acciones** requieren además `now < starts_at` (guardas de la máquina de
  estados). Entre `starts_at` y `expires_at` el link es **solo lectura**.
- Vencido ⇒ `410 manage_link_expired` en las tres rutas, sin mutar nada.

### D4. Resolución y mapeo de errores

`resolve(token)` → `(appointment, clinic, policy)`:

1. formato inválido ⇒ `404 manage_link_not_found` (sin DB);
2. `hash = sha256(token)`; `SELECT` por `manage_token_hash` con las columnas
   necesarias (regla 8, sin `SELECT *`) unido a `clinic`;
3. sin fila ⇒ `404 manage_link_not_found` (mismo cuerpo que el malformado);
4. `now > expires_at` ⇒ `410 manage_link_expired`.

| Caso | Respuesta |
|---|---|
| token malformado / desconocido | `404 manage_link_not_found` |
| token vencido | `410 manage_link_expired` |
| rate-limit excedido | `429 rate_limited` + `Retry-After` |
| Redis caído | `503 manage_unavailable` |
| cuerpo inválido (campo, motivo, nota larga) | `422 invalid_request` (solo nombres de campo) |
| confirmar sobre estado no operable | `409 invalid_transition` |
| confirmar un turno ya iniciado | `409 appointment_started` |
| cancelar un turno pasado | `422 appointment_in_past` |
| cancelar/reprogramar dentro de la ventana | `409 cancellation_window_closed` |
| horario fuera de grilla/horizonte | `422 slot_not_offered` |
| colisión del hueco | `409 slot_taken` + `alternatives` |
| otro request movió el turno | `409 appointment_changed` |

`app/common/exceptions.py` extiende la redacción del 422 de
`_PUBLIC_PREFIX = "/api/booking/"` a `("/api/booking/", "/api/manage/")`: la nota
libre del paciente no puede volver en el cuerpo del error (regla 13).

### D5. Vista de gestión con datos mínimos

```jsonc
{
  "clinic": {"name": "...", "phone": "+541155550100", "timezone": "America/Argentina/Buenos_Aires", "slug": "..."},
  "appointment": {
    "patient_first_name": "María",
    "starts_at": "...", "ends_at": "...",
    "professional_display_name": "...",
    "status": "pending", "origin": "online", "is_overbooking": false
  },
  "policy": {"cancellation_window_hours": 24, "cancellation_closes_at": "..."},
  "actions": {"can_confirm": true, "can_cancel": true, "can_reschedule": true,
             "blocked_reason": null},
  "reason_options": [{"value": "...", "label": "..."}],
  "manage_token_expires_at": "..."
}
```

Solo nombre de pila (primer token de `full_name`) y nunca ids de turno,
paciente, sillón o profesional, ni teléfono/email del paciente: si el link se
reenvía (riesgo aceptado en DD-04), lo que se filtra es lo mínimo para
reconocer el turno. `blocked_reason` ∈ `window_closed | past | not_manageable |
token_expired | null` para que la UI no reimplemente reglas. `reason_options`
sale del servidor (una sola fuente de verdad del catálogo).

`slug` es público (está en el link de reserva) y permite ofrecer "volver a
reservar" tras una cancelación.

### D6. Confirmar

`pending --apply_transition--> confirmed` con
`Actor(clinic_id, type=PATIENT_TOKEN)`, `extra_payload={"source": "manage_link"}`,
mismo `flush` y commit. Con `roles` vacío, `check_transition` no exige rol de
personal y la guarda `NOT_STARTED` sigue aplicando.

- `confirmed` ⇒ replay (D9), no segunda transición.
- `cancelled/absent/no_show/present` ⇒ `409 invalid_transition`.
- `now >= starts_at` ⇒ `409 appointment_started` (se chequea antes para no
  depender del orden interno de las guardas).

### D7. Cancelar

1. Terminal `cancelled` + `action=cancel` ⇒ replay.
2. `now >= starts_at` ⇒ **`422 appointment_in_past`** (RN-CX-05; se traduce acá
   el `409 appointment_started` de la guarda, porque el paciente necesita un
   mensaje distinto al de un turno que ya empezó y todavía no terminó).
3. `starts_at - now < cancellation_window_hours` ⇒
   **`409 cancellation_window_closed`** sin mutar (RN-CX-01). No es 403: el
   recurso es válido, la operación no está disponible online.
4. `apply_transition(CANCELLED)` con `reason=CancellationReason.PACIENTE`,
   `note=payload.note` y `extra_payload={"source": "manage_link",
   "patient_reason": payload.reason}`.

**Mapeo del motivo (decisión con consecuencia).** `appointment.cancellation_reason`
tiene un CHECK que lo exige no nulo y C-13 agrupa por esos 5 valores. Por eso la
**causa** guardada es siempre `paciente` y el **motivo fino** del paciente
(`no_puedo_asistir | enfermedad | viaje | problema_economico | otro`) queda en
`payload.patient_reason`, con la nota libre en `cancellation_note` (≤ 200,
truncada por schema) solo cuando el motivo es `otro`. Consecuencia: el reporte de
cancelaciones por causa de C-13 cuenta estas cancelaciones como `paciente`; el
detalle por motivo queda disponible por evento para un reporte futuro, sin
retro-backfill y **sin tocar C-13**. La nota libre nunca va a logs, ni a eventos
(ni a `payload`), ni a exportaciones.

Alternativa descartada: escribir `payload.reason = <motivo fino>`; C-13 lo
mapearía todo a `otro` y se perdería incluso la causa.

### D8. Reprogramar

Restricciones: mismo profesional (US-021 CA-3 sin flag de política en el modelo),
mismo `appointment_id` (RN-CX-02), un intento por sillón candidato dentro de una
transacción, `EXCLUDE` como barrera final (regla 1).

Se **promueve** `_reschedule` a un método sin commit:

```python
async def reschedule(self, appointment_id, data: Booking, *,
                     event_extra: dict | None = None) -> Appointment:
    """Mueve el turno (sin commit). Devuelve el turno; no-op si nada cambia."""
```

`update()` pasa a delegar en él y mantiene su `commit` y su respuesta, así que
C-05/C-06 no cambian de comportamiento observable. `_reschedule` reutiliza
`lock_resources`, `_resolve` (plantilla, bloqueos, recursos, conflictos), `_write`
(savepoint + traducción de `23P01`) y `record_event`; el `Booking` de destino se
arma con `patient_id` y `manage_token_hash` del turno actual (nunca se pisa el
token ni el origen).

Flujo del paciente:

1. validaciones de estado/ventana igual que D7 (paso 1-3);
2. `starts_at` destino `<= now` ⇒ `422 appointment_in_past`;
3. candidatos = `chairs_on_grid(...)` del profesional para el inicio pedido,
   ordenados por `chair_id`; vacío ⇒ `422 slot_not_offered`;
4. por cada candidato, dentro de un único `begin_nested()` (como
   `_book_first_free` de C-07): `reschedule(...)`; ante `slot_taken`,
   `slot_blocked` o `resource_inactive` se prueba el siguiente; agotados ⇒
   `409 slot_taken` con alternativos calculados con `offerable()` (n=3, 14 días,
   solo `starts_at`/`ends_at`) y rollback;
5. commit y vista actualizada.

`Booking.duration_min` sale de la duración actual del turno: mover no cambia la
práctica. Si el destino cae fuera de la plantilla, `_resolve` responde
`422 outside_schedule`, que el servicio de gestión traduce a `422
slot_not_offered` (el paciente no distingue "fuera de grilla" de "fuera de
horario").

**Alternativa descartada**: `update()` en loop (cada intento commitea → dos
transacciones y un estado intermedio visible para recepción).

### D9. Idempotencia por estado (no por clave)

La operación se define por el **estado deseado**, no por un comando:

| Acción | Estado ya alcanzado | Resultado |
|---|---|---|
| `confirm` | `confirmed` | 200 + evento `updated` `{idempotent_replay: true, action: "confirm"}` |
| `cancel` | `cancelled` | 200 + evento `updated` `{idempotent_replay: true, action: "cancel"}` |
| `reschedule` | `starts_at` igual al pedido | 200 + evento `updated` `{idempotent_replay: true, action: "reschedule"}` |

Se reutiliza el tipo de evento `updated` (ya existe): no se agrega un valor al
enum nativo (`ALTER TYPE … ADD VALUE` no es transaccional y no aporta), y el
reporte de C-13, que lee el último evento `cancelled`, no cuenta dos
cancelaciones. El evento de replay se escribe en la **misma** transacción, así
que "no-op" sigue siendo auditable (Flujo 2, casos de error).

Carreras: dos `confirm` simultáneos → uno gana la transición, el otro espera el
`FOR UPDATE`, ve `confirmed` y escribe replay. Dos `cancel` simultáneos → igual.
Cancelar y reprogramar a la vez: el segundo ve `cancelled` y responde
`409 invalid_transition` (o replay si es cancel). Reprogramar y recepción
moviendo el turno: `409 appointment_changed` (ya implementado en `_reschedule`).

### D10. Rate-limit (por token y por IP, falla cerrada)

Se reutiliza `app/common/rate_limit_guard.consume` y `core/rate_limit.hit`
(Lua, ventana fija). Claves nuevas en `core/rate_limit.py`; el **hash** del token
es la clave (el token nunca entra a Redis):

| Clave | Setting (default) | Cuándo se consume |
|---|---|---|
| `rl:manage:read:ip:{ip}` | `MANAGE_READ_IP_RATE_LIMIT="120/60s"` | antes de resolver el token |
| `rl:manage:read:token:{sha256}` | `MANAGE_READ_TOKEN_RATE_LIMIT="60/60s"` | antes de la DB, solo token bien formado |
| `rl:manage:write:ip:{ip}` | `MANAGE_WRITE_IP_RATE_LIMIT="30/60s"` | antes de validar el cuerpo (un 422 gasta) |
| `rl:manage:write:token:{sha256}` | `MANAGE_WRITE_TOKEN_RATE_LIMIT="10/60s"` | ídem |

Doble cubo porque protegen cosas distintas: el de IP frena el barrido de tokens
(no se crean claves por tokens inventados: solo se consume el de token si el
formato es válido) y el de token frena el doble click enloquecido sobre el mismo
link. Redis caído ⇒ `503 manage_unavailable` (nunca degradar a permitir). El IP
sale de `common/request_meta.client_ip` (D11 de C-07), sin parsear
`X-Forwarded-For` en la app.

### D11. Invalidación de recordatorios (puerto, no tabla)

```python
class ReminderInvalidator(Protocol):
    async def invalidated(self, session: AsyncSession, appointment: Appointment, *,
                          action: Literal["confirm", "cancel", "reschedule"]) -> None: ...

class NoopReminderInvalidator:  # v1
    async def invalidated(self, session, appointment, *, action): return None
```

Se inyecta con `Depends(get_reminder_invalidator)` (mismo patrón que `BotGuard`
de C-07) y se invoca dentro de la transacción, después de la mutación y antes
del commit. C-09 reemplaza el `get_reminder_invalidator` por la implementación
real (marcar `cancelled` los `reminder_job` pendientes y reprogramar los futuros)
sin tocar router, servicio ni specs. El test usa un spy por override de
dependencia.

**Alternativa descartada**: crear `reminder_job` en C-08 — duplicaría el change
de C-09 y adelantaría migraciones de otro change (regla 3: una revisión por
change).

### D12. Migración `c08_manage_token` (una sola revisión)

Único cambio de schema necesario: el teléfono de contacto de la clínica.

1. `ALTER TABLE clinic ADD COLUMN contact_phone text` (nullable, sin default ⇒
   metadata-only, sin reescritura).
2. `ALTER TABLE clinic ADD CONSTRAINT clinic_contact_phone_length CHECK
   (contact_phone IS NULL OR char_length(contact_phone) BETWEEN 6 AND 32) NOT
   VALID;` y luego `VALIDATE CONSTRAINT` (regla 11; `ADD CONSTRAINT … NOT VALID`
   no toma lock de tabla).
3. Sin índices nuevos: `contact_phone` no se filtra ni ordena.
4. Downgrade: `DROP CONSTRAINT`, `DROP COLUMN`.

`appointment` **no** cambia (columna, CHECKs e índice ya existen de C-07). Si
durante el apply apareciera otra necesidad de schema, entra en esta **misma**
revisión; no se crea una segunda.

El modelo `Clinic` declara la columna y el CHECK para el test de drift.

### D13. Settings y `.env.example` (regla 6)

Nuevos: `MANAGE_READ_IP_RATE_LIMIT`, `MANAGE_READ_TOKEN_RATE_LIMIT`,
`MANAGE_WRITE_IP_RATE_LIMIT`, `MANAGE_WRITE_TOKEN_RATE_LIMIT` (validados con
`parse_window_spec` al arrancar) y `MANAGE_TOKEN_TTL_H` con `ge=1` (ya existe,
hoy sin validador). Todos en `.env.example` sin valores secretos.

### D14. Frontend `/g/:token`

- `features/manage/`: `api.ts` (fetch anónimo con `credentials: "omit"`, tipos de
  borde en `types.ts`, sin `any`), `queries.ts` (TanStack), `useManageActions`
  (estado de la acción en curso, bloqueo del doble envío, invalidación de la
  query), componentes PascalCase `ManageSummary`, `ConfirmAction`,
  `CancelDialog`, `ReschedulePanel`, `ManageContact`, `ManageError`.
  `pages/ManagePage.tsx` solo compone.
- **QueryClient propio** para la ruta pública, igual que `BookingFlow`: el
  `AuthProvider` hace `queryClient.clear()` cuando el visitante resulta anónimo
  (hallazgo del E2E de C-07) y colgaría la vista.
- Fechas con los helpers de `shared/time` en la zona de la clínica que devuelve
  la vista; ningún cálculo de ventana en el cliente (se usa `actions` y
  `blocked_reason` del servidor).
- Mobile-first de una columna, botones ≥ 44 px, confirmación de la acción
  destructiva en un diálogo, `aria-live` para carga/errores,
  `prefers-reduced-motion` respetado, tokens de Tailwind existentes (`enamel`,
  `dental-*`).
- `409 slot_taken` muestra los alternativos como botones que reenvían la misma
  acción con el horario elegido.

## Sequencias

**Confirmar**

```
PATCH /api/manage/{t} {action:confirm}
  → rate-limit IP → rate-limit token → resolve(hash) → 404/410
  → now >= starts_at? → 409 appointment_started
  → status confirmed? → replay(updated)                  [commit]
  → status ∈ {pending}? → apply_transition(confirmed, patient_token)
                         → ReminderInvalidator.invalidated("confirm")
                         → commit → 200 vista
```

**Cancelar**

```
PATCH {action:cancel, reason?, note?}
  → rate-limit → resolve → 404/410
  → status cancelled? → replay(updated)                  [commit]
  → status ∉ {pending, confirmed}? → 409 invalid_transition
  → now >= starts_at? → 422 appointment_in_past
  → starts_at - now < ventana? → 409 cancellation_window_closed (sin mutar)
  → apply_transition(cancelled, cause=paciente, note, patient_reason)
    → ReminderInvalidator.invalidated("cancel") → commit → 200
```

**Reprogramar**

```
PATCH {action:reschedule, starts_at}
  → rate-limit → resolve → 404/410
  → estado/ventana → 409
  → starts_at == actual? → replay(updated)                [commit]
  → candidatos = chairs_on_grid(prof, starts_at); vacío → 422 slot_not_offered
  → begin_nested()
      for chair in candidatos:
          reschedule(id, Booking(...chair...))  → locks prof → chair
             ok → break ; slot_taken/blocked/inactive → next
      agotados → rollback → 409 slot_taken + alternatives(offerable, n=3)
  → ReminderInvalidator.invalidated("reschedule")
  → commit → 200 vista
```

## Estrategia de pruebas

| Capa | Qué cubre | Cómo |
|---|---|---|
| DB / migración | columna + CHECK, drift modelo↔migración, `upgrade → downgrade -1 → upgrade` | pytest contra Postgres 15 real |
| Invariante | dos reprogramaciones concurrentes al mismo hueco; EXCLUDE como barrera (mutar el pre-chequeo no rompe la garantía) | `asyncio.gather` con dos sesiones, 20 rondas |
| API | 404/410/409/422/429/503, vista sin PII, catálogo de motivos, cabeceras, 422 sin eco | httpx + `caplog` |
| Idempotencia | las tres acciones repetidas, carreras de confirm/cancel | API + DB |
| Tenancy | token de otra clínica, disponibilidad sin cruzar clínicas, mutación de B no visible en A | API |
| Frontend | estados, doble toque, ventana cerrada, 409 con alternativos, storage vacío | Vitest + MSW |
| E2E | confirmar, cancelar y reprogramar desde el link real en móvil 360 px | Playwright |

Regla 9: sin mocks de DB ni de Redis en invariantes. Regla 13: solo datos
sintéticos (`María Ficticia`, `+54 11 5555-0100`, `@example.com`).

## Risks / Trade-offs

- [Un link reenviado deja gestionar el turno a quien lo tenga] → riesgo aceptado
  en DD-04; se minimiza con TTL absoluto, rate-limit por token, datos mínimos
  (nombre de pila) y acciones auditadas. Rotar en reprogramación queda como
  decisión abierta #1.
- [No rotar el token deja links viejos de WhatsApp vivos hasta el TTL] → el link
  apunta al mismo turno, así que el alcance no crece; la rotación se puede
  activar después sin migración (solo `UPDATE` del hash).
- [El motivo fino no se agrega al reporte de C-13] → causa `paciente` + detalle
  por evento; un reporte por motivo es un change posterior, sin backfill.
- [El teléfono de la clínica es dato operativo público] → solo se expone con un
  token válido o en la vista pública de reserva; nunca junto a datos del
  paciente.
- [Reprogramar dentro de la ventana está bloqueado online (RN-CX-02)] → el
  paciente puede llamar; recepción sigue pudiendo mover el turno.
- [Reintentar sillones alarga el lock del profesional] → 1–3 intentos en la
  práctica; mismo patrón ya usado por C-07.
- [Un `410` confirma que el token existió] → el espacio de tokens es de 256 bits;
  el rate-limit por IP hace inviable el barrido.
- [Nota libre del paciente = posible PII en la base] → ≤ 200 caracteres, nunca en
  logs, ni en `payload` de eventos, ni en exportaciones; el 422 público no la
  ecoa.

## Migration Plan

1. `alembic upgrade head` (`c08_manage_token`): columna nullable + CHECK
   `NOT VALID → VALIDATE`. Sin downtime y sin reescritura.
2. Deploy API + SPA. La ruta `/g/:token` ya existe: no hay cambio de routing.
   El teléfono se carga desde `PATCH /api/clinic/policies` (admin) o por seed.
3. Si una clínica no tiene `contact_phone`, la pantalla de derivación muestra el
   nombre de la clínica sin teléfono (degradación explícita, no error).
4. Rollback: `downgrade -1` quita la columna y el CHECK; el link de gestión
   deja de existir si se revierte también el deploy (no hay estado nuevo en
   `appointment` que se pierda: los eventos ya escritos son append-only e
   inmutables, por diseño).

## Open Decisions — approved (2026-11-05, by user)

Las cinco se aprobaron con su default tal como está escrito abajo.

1. **Rotación del `manage_token` al reprogramar** (pregunta Alta de
   `10_preguntas_abiertas.md`). *Default propuesto*: **no rotar**. El token es de
   un turno, el TTL es absoluto y la reprogramación no cambia el dueño.
   Consecuencia: un link viejo en un chat sigue funcionando hasta el TTL (mismo
   riesgo ya aceptado en DD-04). Si se aprueba rotar: el link anterior deja de
   servir, hay que reenviar el nuevo (C-09/C-10 todavía no notifican, así que en
   v1 el paciente vería el link nuevo solo en la respuesta de la página), y la
   respuesta debería incluir el `manage_url` nuevo. No requiere migración.
2. **Semántica del TTL**. *Default*: 72 h contadas desde `ends_at` del turno
   (RN-ON-04 "post-turno"); antes de `starts_at` el link permite acciones, entre
   `starts_at` y `expires_at` es solo lectura, y después responde `410`. No se
   extiende al confirmar ni al reprogramar (TTL absoluto, para que un link no
   viva para siempre). Alternativa: contar desde el último cambio de estado;
   extiende la vida del link en turnos reprogramados muchas veces.
3. **Lista cerrada de motivos del paciente**. *Default*:
   `no_puedo_asistir`, `enfermedad`, `viaje`, `problema_economico`, `otro`.
   `reason` es opcional (si falta, no se registra `patient_reason` y la causa
   sigue siendo `paciente`); el texto libre solo aplica a `otro` y se limita a
   **200 caracteres** en `cancellation_note`. Cambiar la lista es cambiar el
   catálogo en un solo lugar (servidor) y sus tests.
4. **Alcance del rate-limit**. *Default*: **ambos**, por IP y por hash de token,
   con cubos separados de lectura y escritura: lectura `120/60s` por IP y
   `60/60s` por token; escritura `30/60s` por IP y `10/60s` por token. Solo por
   IP dejaría un doble click enloquecido consumiendo la cuota de toda una red
   NAT; solo por token no frena el barrido. Valores en env, calibrables en
   piloto sin tocar código.
5. **Respuesta de la reprogramación**. *Default*: **no** devuelve token ni URL;
   devuelve la misma vista de gestión y el paciente conserva el link de la barra
   de direcciones. Coherente con el default de no rotar. Si se aprueba rotar
   (decisión 1), esta respuesta pasa a incluir `manage_url` y la tarea 8.x debe
   actualizarse; es el único punto donde ambas decisiones se tocan.

## UI Mockups

- Design system revision: 1 (`design-system/README.md`, `Approval: approved (2026-11-05, by user)`)
- Decision: yes (2026-11-05)
- Mockups: `openspec/changes/c-08-gestion-por-token/mockups/`
- Approval: approved (2026-11-05, by user)
- Preview: rendered (2026-11-05) — `mockups/previews/*-390x844.png` y `*-1440x900.png`
- Visual verify: pending (se completa en la fase de verify)
- Desvíos intencionales de la implementación (2026-11-05, apply):
  - **Sin sillón** en el detalle del turno: los mockups muestran «Sillón 1», pero el spec
    `booking/manage-token` prohíbe exponer el sillón y la vista no lo trae (D5).
  - **Etiquetas de los botones** según el spec `web/manage-token`: «Confirmar turno»,
    «Cambiar horario» y «Cancelar» (los mockups dicen «Confirmar asistencia»,
    «Reprogramar» y «Cancelar turno»).
  - **Vencimiento del link**: se muestra la fecha que devuelve el servidor
    (`manage_token_expires_at`) en vez del texto fijo «72 h», porque el TTL es configurable.
  - **Pantalla de link no disponible** (`06-expired`): sin botón «Reservar un turno nuevo»,
    porque ni el `404` ni el `410` traen el slug de la clínica; el `410` sí trae nombre y
    teléfono. «Reservar un turno nuevo» se ofrece en la vista de un turno cancelado.
  - Estilos con los tokens Tailwind existentes (`enamel`, `dental-*`), no con
    `design-system/tokens.css`.

Pantallas maquetadas y aprobadas antes del apply (proyecto en modo `system-and-mockups`):

| Mockup | Estado | Capturas |
|---|---|---|
| `01-pending.html` | Turno `pending` con las tres acciones + plazo de cancelación | `previews/01-pending-{390x844,1440x900}.png` |
| `02-confirmed.html` | Post-confirmación, replay idempotente | `previews/02-confirmed-{390x844,1440x900}.png` |
| `03-cancel.html` | Cancelación con motivo (lista cerrada + «Otro» ≤200) | `previews/03-cancel-{390x844,1440x900}.png` |
| `04-window-closed.html` | Fuera de ventana → derivación a la clínica (`409 cancellation_window_closed`) | `previews/04-window-closed-{390x844,1440x900}.png` |
| `05-reschedule.html` | Reprogramación con días y huecos válidos (`409 slot_taken` → recarga) | `previews/05-reschedule-{390x844,1440x900}.png` |
| `06-expired.html` | Token vencido/inexistente → contacto (`410`/`404`) | `previews/06-expired-{390x844,1440x900}.png` |

Los seis importan `design-system/tokens.css` y `design-system/brand.js`; el nombre
del producto y el logo siguen `(TBD)`. Estos mockups son criterio de aceptación
visual en `tasks.md` y se comparan contra la implementación durante el verify.

## Open Questions

- Nada que bloquee el apply. Los valores finales de los cupos, del catálogo de
  motivos y del TTL son settings/env y se calibran con el piloto.
- El texto legal de privacidad sigue pendiente de asesoría (pregunta Alta de
  `10_preguntas_abiertas.md`), pero la página de gestión no recolecta datos
  nuevos: solo reutiliza el consentimiento ya registrado en la reserva.
