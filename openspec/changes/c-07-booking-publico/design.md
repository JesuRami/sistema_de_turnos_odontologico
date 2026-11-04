# Design — C-07 `booking-publico`

## Context

- C-01 dejó el stub `app/modules/booking_public` (`/booking-public/ping`), la
  ruta SPA `/b/:slug` con un placeholder y un rate-limit global **en memoria**
  (`GlobalRateLimitMiddleware`, setting `BOOKING_RATE_LIMIT="30/minute"`, que pese
  al nombre es global).
- C-02 dejó `clinic.slug` único, `clinic.booking_enabled` (default `false`),
  `professional.booking_enabled`, `patient` con `CHECK` de contacto, E.164,
  `privacy_consent_at/version` y `normalize_phone_e164` +
  `find_patients_by_phone` (familias: teléfono no único).
- C-03 dejó el rate-limit **en Redis** de ventana fija (`core/rate_limit.hit`, Lua
  atómico, fail-closed `503`) y `_client_ip` sobre `request.client.host`; en
  producción uvicorn confía en `X-Forwarded-For` que nginx **sobrescribe** con
  `$remote_addr` (`compose.prod.yaml` → `FORWARDED_ALLOW_IPS`).
- C-05 dejó `AppointmentsService.book(data, origin=online)` — lock `FOR UPDATE`
  profesional → sillón, validación de horario/bloqueos/colisiones, `EXCLUDE`
  como última barrera, traducción de `23P01` a `409 slot_taken` con `conflicts`
  y alternativos **por par profesional-sillón** — y la función pura
  `suggest_slots`. `Booking` exige `chair_id`; `Actor` admite
  `ActorType.PATIENT_TOKEN`.
- La regla semanal es única por (profesional, sillón, día, franja): un
  profesional puede atender la misma hora en dos sillones.
- Hoy la cabeza de Alembic es `c13_event_slot` (C-13 en curso).

Motivación y alcance: `proposal.md`. Comportamiento exigido: `specs/`.

## Goals / Non-Goals

**Goals:**
- Un único camino de escritura: la reserva online es una llamada a
  `AppointmentsService.book`, nunca un `INSERT` propio (contrato de C-05 y
  enganche futuro de C-09).
- Que nada de lo que devuelve un endpoint anónimo permita reconstruir quién
  atiende a quién: solo horarios libres por profesional.
- Superficie anti-abuso concreta y medible en v1, extensible a CAPTCHA sin tocar
  el router.

**Non-Goals:**
- Consumir el token (C-08), programar jobs o enviar mensajes (C-09/C-10), tabla
  `consent` (C-09/C-10), push/SSE a la agenda.

## Decisions

### D1. Superficie pública: tres endpoints bajo `/api/booking/{slug}`

| Método | Ruta | Cupo Redis |
|---|---|---|
| `GET` | `/api/booking/{slug}` | lectura por IP |
| `GET` | `/api/booking/{slug}/availability?professional_id&from&to` | lectura por IP |
| `POST` | `/api/booking/{slug}/appointments` | reserva por IP + por slug |

El router `booking_public` reemplaza al stub (`/booking-public/ping` se elimina;
el test de cableado de C-01 se actualiza). Router fino → `BookingPublicService`.
Sin dependencia de `Principal`: la clínica se resuelve **solo** por slug
(`booking_enabled=true`), y todo lo demás se filtra por ese `clinic_id`
(regla 4). Slug inexistente o deshabilitado → mismo `404 booking_not_found`
(misma consulta, mismo cuerpo).

Respuestas con `Cache-Control: no-store` (disponibilidad cambia; la reserva
lleva el token) y `Referrer-Policy: no-referrer` en la reserva.

### D2. Anti-bot v1: rate-limit + anti-enumeración, sin CAPTCHA (decisión del usuario, 2026-11-04)

Resuelve la pregunta Alta de `10_preguntas_abiertas.md`. Capas:

1. **Rate-limit Redis** (reutiliza `core/rate_limit.hit`, se extrae el
   `_consume` de auth a `app/common/rate_limit_guard.py` parametrizando el código
   de indisponibilidad: `auth_unavailable` / `booking_unavailable`):
   - `rl:booking:create:ip:{ip}` — `PUBLIC_BOOKING_IP_RATE_LIMIT="10/3600s"`
     (RN-ON-03). Se consume **antes** de validar el cuerpo: un 422 también gasta.
   - `rl:booking:create:slug:{clinic_id}` — `PUBLIC_BOOKING_SLUG_RATE_LIMIT=
     "300/3600s"`; se consume solo con slug resuelto (no se crean claves Redis
     por slugs inventados).
   - `rl:booking:read:ip:{ip}` — `PUBLIC_BOOKING_READ_RATE_LIMIT="120/60s"`,
     antes de resolver el slug (el barrido de slugs también se frena).
   - Redis caído → `503 booking_unavailable` (fail-closed, igual que auth).
2. **Anti-enumeración**: 404 idénticos (slug, profesional no reservable/ajeno);
   rango ≤ 14 días y horizonte `PUBLIC_BOOKING_HORIZON_DAYS=60`; la respuesta no
   lleva sillón, estado, ids de turnos ni conteos (RN-ON-01).
3. **`BotGuard`** (punto de extensión):

   ```python
   class BotGuard(Protocol):
       async def verify(self, request: Request, *, action: Literal["read", "book"]) -> None: ...
   class NoopBotGuard:  # v1
       async def verify(self, request, *, action): return None
   ```

   Inyectado como dependencia FastAPI (`get_bot_guard`) en el `POST`. Rechazo →
   `DomainError(403, "bot_check_failed")`. Un futuro Turnstile/reCAPTCHA lee su
   token de una cabecera (`X-Bot-Token`), así que no cambia el schema
   (`extra='forbid'`) ni el router: solo la implementación que devuelve
   `get_bot_guard` (seleccionada por setting `BOT_GUARD=noop`). Se testea con
   override de dependencia que rechaza.

Alternativas descartadas: Turnstile/reCAPTCHA ya (decisión del usuario: fricción
y dependencia externa para un piloto chico); rate-limit en memoria (no se
comparte entre réplicas ni sobrevive reinicios).

### D3. Disponibilidad pública = unión por sillón de `suggest_slots`

Para el profesional reservable, en una sola pasada y solo con columnas
necesarias (regla 8):

1. reglas activas del profesional sobre sillones activos, agrupadas por sillón;
2. bloqueos vigentes del profesional **o** de esos sillones en el rango;
3. ocupados (`starts_at, occupied_until`) vigentes —incluidos sobreturnos— del
   profesional o de esos sillones, en la clínica.

Por cada sillón se llama `suggest_slots(reglas_del_sillón, blocks=bloqueos(prof
∪ sillón), busy=ocupados(prof ∪ sillón), desde=from, horizon=to-from, n=cap)`
con la duración de la regla y el buffer del profesional; se unen por
`starts_at` (dedupe) y se ordenan. `cap = 500` por respuesta. Se devuelve
`{timezone, slots: [{starts_at, ends_at, professional_id}]}`.

El cálculo vive en `booking_public/availability.py` como función pura sobre
datos ya leídos (testeable sin DB, como `suggest_slots`). Es el **mismo**
cálculo que valida la reserva (D4) y arma los alternativos del 409 (D6): una
sola definición de "hueco ofrecible".

Índices: alcanzan los de C-05 (`(professional_id, starts_at)`, EXCLUDE gist por
sillón) y C-04; se verifica con `EXPLAIN` en el test de rendimiento liviano, sin
índice nuevo salvo evidencia.

### D4. Reserva: grilla + selección de sillón por el servidor

Cuerpo (`extra='forbid'`): `professional_id`, `starts_at` (con zona; sin zona →
422), `patient: {full_name, phone?, email?, whatsapp_opt_in: bool (requerido si
hay phone), privacy_accepted: bool}`. No hay `chair_id`, `duration_min`,
`status`, `origin` ni `clinic_id`: el paciente elige entre huecos pre-calculados
(RN-AG-03).

Orden dentro de **una** transacción:

1. `BotGuard.verify` → cupos IP/slug → resolver clínica y profesional reservable
   (`404`) → validar contacto (D5).
2. Candidatos: sillones activos cuya regla vigente genera exactamente
   `starts_at` en su grilla (si ninguno → `422 slot_not_offered`;
   `starts_at <= now` → `422 appointment_in_past`), ordenados por `chair_id`.
3. Match-o-alta del paciente (D7).
4. Para cada sillón candidato: `book(Booking(patient, prof, chair, starts_at,
   duration_min=None, manage_token_hash=h), origin=ONLINE)`. Si lanza un `409`
   (el pre-chequeo bajo lock no escribe; la violación del EXCLUDE ya queda
   contenida en el savepoint de `_write`), se prueba el siguiente sillón; si se
   agotan, se arma el 409 público (D6). El lock
   es siempre profesional → sillón (el profesional queda tomado desde el primer
   intento; los sillones se toman en orden de id), así que no hay ciclo con
   recepción ni con bloqueos.
5. Commit. Si el 409 final ocurre, **rollback total**: no queda paciente nuevo.

Cambios mínimos en C-05: `Booking` suma `manage_token_hash: bytes | None = None`
y `book()` acepta `event_extra: dict | None` que se mezcla en el payload del
evento `created` (canal elegido, `whatsapp_opt_in_granted`). Nada más del
servicio cambia.

Alternativa descartada: que el cliente elija el sillón (expone recursos internos
y abre enumeración de ocupación por sillón).

### D5. Contacto y canal (RN-ON-02, Flujo 1 casos de error)

| Teléfono | `whatsapp_opt_in` | Email válido | Resultado |
|---|---|---|---|
| válido | `true` | — | 201, `channel=whatsapp` |
| válido | `false` | sí | 201, `channel=email`, aviso `whatsapp_declined_email_channel` |
| válido | `false` | no | `422 whatsapp_opt_in_required` |
| inválido | — | sí | 201, teléfono **descartado**, `channel=email`, aviso `phone_invalid_email_channel` |
| inválido | — | no | `422 contact_required` |
| ausente | — | sí | 201, `channel=email` |
| ausente | — | no | `422 contact_required` |

`privacy_accepted` debe ser `true` (`422 privacy_consent_required`); se guarda
`privacy_consent_at=now` y `privacy_consent_version=PRIVACY_POLICY_VERSION`
(setting nuevo). Email: validación sintáctica de Pydantic (`EmailStr`),
normalizado a minúsculas. Mensajes de error genéricos, sin el valor recibido
(reutiliza los de `clinic/service`, regla 13).

**Decisión propia (a revisar):** RN-ON-02 dice "opt-in explícito si deja
teléfono". Se interpreta como *elección explícita*, no como opt-in forzado: un
consentimiento obligatorio para reservar no es libre (Ley 25.326). Quien rechaza
WhatsApp reserva igual si deja email.

### D6. 409 público

`book()` levanta `slot_taken` con `conflicts` (ids de turnos ajenos) y
alternativos con `chair_id`: **no** se reenvía. El servicio público captura el
`DomainError(409, "slot_taken")`, hace rollback y responde `409 slot_taken
{alternatives: [{starts_at, ends_at, professional_id}]}` calculados con D3 desde
`starts_at`, `n=3`, horizonte 14 días. Otros 409 de `book()`
(`resource_inactive`, `slot_blocked`) se reducen a `409 slot_taken` también (para
el paciente es "ese horario ya no está"; no se filtra el motivo interno).

### D7. Match de paciente (RN-ON-05) sin duplicados por carrera

- Teléfono válido: `find_patients_by_phone` y se elige el primero cuyo
  `lower(btrim(full_name))` coincide (mismo criterio de duplicado que C-05 D11).
  Sin coincidencia de nombre → paciente nuevo (familias).
- Sin teléfono válido (solo email): **siempre paciente nuevo**; los duplicados
  se resuelven con la fusión asistida de C-06. **Decisión propia (a revisar)**:
  no se matchea por email para no ampliar RN-ON-05.
- Carrera de dos reservas simultáneas del mismo paciente nuevo:
  `pg_advisory_xact_lock(hashtextextended(clinic_id || phone_e164, 0))` antes del
  match, liberado al fin de la transacción.
- Paciente existente: nunca se pisa nombre, teléfono ni email. Solo se activa
  `whatsapp_opt_in` (`false → true`) si el paciente lo marcó, y se actualiza el
  consentimiento de privacidad a la versión vigente. **Decisión propia (a
  revisar)**: quien conozca nombre + teléfono de un paciente podría activar su
  opt-in; el efecto es que el titular reciba recordatorios de un turno a su
  nombre, y el `STOP` de C-10 lo revierte.

### D8. `manage_token` (DD-04, RN-ON-04)

- `token = secrets.token_urlsafe(32)` (256 bits, 43 caracteres URL-safe).
- `manage_token_hash = sha256(token).digest()` → `bytea` de 32 bytes. SHA-256
  sin sal es suficiente: el token tiene 256 bits de entropía (no es una
  contraseña), y permite lookup por igualdad en C-08.
- Se devuelve una sola vez: `manage_url = f"{FRONTEND_PUBLIC_URL}/g/{token}"`.
  Nunca va al evento, a logs ni a otra respuesta; el test lo busca en
  `appointment_event.payload` y en `caplog`.
- TTL (72 h post-turno, `MANAGE_TOKEN_TTL_H` ya existe) y rotación en
  reprogramación: **C-08** (decisión del usuario). C-07 no agrega columna de
  expiración: se deriva de `ends_at`.

### D9. Actor del evento

`Actor(clinic_id, type=ActorType.PATIENT_TOKEN)` sin `user_id`. El enum ya lo
tiene y el CHECK de `appointment_event` lo admite. **Decisión propia (a
revisar)**: se usa `patient_token` (el paciente es el titular del token emitido
en esa misma transacción) en lugar de agregar un valor `public` al enum, que
exigiría `ALTER TYPE ... ADD VALUE` y otra fuente de verdad para los reportes.
El payload lleva `origin=online` y `channel`.

### D10. Migración `c07_booking_public`

`down_revision` = cabeza vigente al aplicar (hoy `c13_event_slot`; si C-13 suma
otra revisión antes, se rebasa). Pasos (regla 11):

1. `ALTER TABLE appointment ADD COLUMN manage_token_hash bytea` (nullable, sin
   default: metadata-only).
2. `CHECK (manage_token_hash IS NULL OR octet_length(manage_token_hash) = 32)`
   y `CHECK (origin <> 'online' OR manage_token_hash IS NOT NULL)` como `NOT
   VALID`, luego `VALIDATE CONSTRAINT` (si hubiera turnos online previos sin
   hash, la migración falla explícitamente: hoy no existen porque no hay
   endpoint).
3. `CREATE UNIQUE INDEX CONCURRENTLY uq_appointment_manage_token_hash ON
   appointment (manage_token_hash) WHERE manage_token_hash IS NOT NULL` en
   `autocommit_block` (patrón de C-05).

Downgrade inverso (`DROP INDEX CONCURRENTLY`, drop constraints, drop column). El
modelo `Appointment` declara columna, CHECKs e índice para el test de drift.

### D11. IP de cliente

Se extrae `client_ip(request)` a `app/common/request_meta.py` y lo usan auth y
booking. Confía en lo que uvicorn ya resolvió (`--proxy-headers` +
`FORWARDED_ALLOW_IPS`, con nginx sobrescribiendo `X-Forwarded-For`); la app
**no** parsea `X-Forwarded-For` por su cuenta (sería falsificable en dev).

### D12. Frontend `/b/:slug`

- `features/booking/`: `api.ts` (fetch con `credentials: "omit"`, tipos de borde
  en `types.ts`, sin `any`), `useBookingFlow` (`useReducer` con pasos
  `professional | day | time | contact | done`), componentes PascalCase
  `ProfessionalStep`, `DayStep`, `TimeStep`, `ContactStep`, `Confirmation`,
  `BookingError`. `pages/BookingPage.tsx` solo compone.
- Datos con TanStack Query (ya instalado): catálogo y disponibilidad por ventana
  de 14 días (prefetch de la siguiente al navegar), `staleTime` 0 en
  disponibilidad. Agrupado por día local con los helpers de zona de
  `shared/time` (C-06): todo en la zona de la clínica.
- Estado solo en memoria: ni el token ni los datos tocan `localStorage`/
  `sessionStorage`.
- Diseño (`frontend-design`): una sola columna mobile-first, horarios como
  botones de 44 px en grilla de 3–4 columnas, el elemento memorable es la
  confirmación con el link de gestión y un botón "Copiar link". Copy en voz
  activa ("Confirmar turno", "Ese horario se acaba de ocupar"). Tokens de
  Tailwind existentes (`enamel`, `dental-*`). Respeta `prefers-reduced-motion`.
- 409: los alternativos se muestran como botones; elegir uno vuelve a enviar con
  los mismos datos.

### D13. Agenda de recepción en "tiempo real"

`refetchInterval: 30_000` en la query del rango visible de la agenda (C-06),
con el comportamiento por defecto de TanStack (no refetch con pestaña oculta) y
el `refetchOnWindowFocus` ya global. **Decisión propia (a revisar)**: polling en
vez de SSE/WebSocket: < 50 usuarios concurrentes por tenant (KB 08) y un request
liviano cada 30 s por pestaña; SSE queda para cuando haya otra necesidad de push.

### D14. Settings nuevos (regla 6)

`PUBLIC_BOOKING_IP_RATE_LIMIT`, `PUBLIC_BOOKING_SLUG_RATE_LIMIT`,
`PUBLIC_BOOKING_READ_RATE_LIMIT`, `PUBLIC_BOOKING_HORIZON_DAYS`,
`PRIVACY_POLICY_VERSION`, `BOT_GUARD`, en `settings.py` (validados con
`parse_window_spec`) y `.env.example`. `BOOKING_RATE_LIMIT` (global en memoria)
no se toca para no romper C-01; se documenta que es el tope global.

## Risks / Trade-offs

- [Sin CAPTCHA, un atacante con muchas IPs puede llenar la agenda con
  `pending` falsos] → cupo por slug (techo absoluto por clínica), los `pending`
  quedan destacados en recepción (C-06) y C-08/C-09 los liberan si no confirman;
  el `BotGuard` permite activar CAPTCHA con un cambio de configuración +
  implementación.
- [La disponibilidad revela ocupación por diferencia (hueco ausente = ocupado o
  bloqueado)] → inherente a mostrar huecos; se acota con rango, horizonte y cupo
  de lecturas, y no se distingue ocupado de bloqueado.
- [IP compartida (NAT de un hospital/universidad) agota el cupo de 10/h] →
  configurable por env; el 429 dice cuándo reintentar.
- [Opt-in activado por un tercero que conoce nombre + teléfono] → ver D7;
  reversible por `STOP` (C-10) y auditado en el evento.
- [Pacientes solo-email se duplican] → fusión asistida de C-06.
- [Reintento de sillones dentro de la misma transacción alarga el lock del
  profesional] → como mucho tantos intentos como sillones con regla en ese
  horario (1–3 en la práctica).
- [Migración depende de la cabeza de C-13] → `down_revision` se fija al aplicar
  y el CI corre `upgrade → downgrade -1 → upgrade`.
- [Texto legal de privacidad aún sin validar (pregunta Alta Ley 27.706/26.529)]
  → se versiona (`PRIVACY_POLICY_VERSION`) para poder re-consentir cuando el
  asesor lo defina; el texto en la página es placeholder marcado.

## Migration Plan

1. Deploy de la migración `c07_booking_public` (sin downtime: columna nullable,
   CHECKs `NOT VALID → VALIDATE`, índice `CONCURRENTLY`).
2. Deploy de API + frontend. `clinic.booking_enabled` sigue en `false` por
   default: cada clínica se habilita a mano (seed de la clínica demo con `true`
   para E2E).
3. Rollback: deshabilitar `booking_enabled` corta la superficie pública sin
   redeploy; `downgrade -1` quita columna e índice (pierde los hashes: los links
   emitidos dejan de servir, se advierte en el README).

## Open Questions

- Valores finales de los cupos por slug y de lectura: se calibran con el piloto
  (son env vars, no cambian diseño ni tasks).
