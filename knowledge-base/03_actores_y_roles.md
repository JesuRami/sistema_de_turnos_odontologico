# Actores y Roles

## Actores del sistema

| Actor | Descripción | Cómo interactúa |
|-------|-------------|-----------------|
| Administrador de clínica | Dueño o encargado; configura el sistema y mide resultados | SPA autenticada: profesionales, sillones, horarios, bloqueos, reportes, usuarios |
| Recepción | Personal de mostrador/teléfono; opera la agenda día a día | SPA autenticada: agenda día/semana, crear/mover/cancelar turnos, sobreturnos, lista de espera, confirmaciones manuales |
| Odontólogo | Profesional que atiende; consulta su agenda y bloquea disponibilidad | SPA autenticada (vista restringida): mis turnos, mis bloqueos, marcar presente/ausente |
| Paciente | Persona que reserva y gestiona sus turnos | Link público de reserva (sin cuenta) + links con token por turno (confirmar/cancelar/reprogramar) + WhatsApp |
| Sistema (actor técnico) | Worker de recordatorios y webhook de WhatsApp | Jobs programados y eventos entrantes; actúa con identidad de servicio, todo auditado |

**Suposición:** 4 actores humanos. No hay rol de "auditor externo", "gerenciadora" ni "círculo" en v1.0; esos actores pertenecen a la fase de obras sociales y no tienen superficie en el MVP.

## RBAC — Matriz de permisos

RBAC simple rol → permiso (sin ABAC, sin permisos por registro salvo "odontólogo solo ve sus turnos").

| Recurso | Admin | Recepción | Odontólogo | Paciente (token) |
|---------|-------|-----------|------------|------------------|
| Usuarios y roles | CRUD | — | — | — |
| Profesionales / sillones / horarios | CRUD | R | R (propios) | R (disponibilidad pública) |
| Bloqueos de agenda | CRUD | CR (con motivo) | CR (propios) | — |
| Turnos (crear) | CRUD | CRUD | R | C (solo propios, vía booking) |
| Turnos (estados: confirmar, presente, ausente, cancelar) | CRUD | CRUD | U (presente/ausente en sus turnos) | U (confirmar/cancelar/reprogramar solo su turno vía token) |
| Sobreturnos | CRUD | C (con flag explícito) | — | — |
| Lista de espera | CRUD | CRUD | R | C (anotarse) / U (aceptar/rechazar oferta) |
| Reportes | R | R (operativos) | R (propios) | — |
| Auditoría | R | — | — | — |
| Exportación | CRUD (ejecutar) | — | — | — |

Reglas transversales:

- El odontólogo **no puede** crear turnos ni ver la agenda de otros profesionales (principio de mínimo privilegio; evita filtraciones entre profesionales que comparten clínica).
- Recepción **no accede** a datos clínicos (hoy no existen; la regla se deja escrita para que la fase clínica la herede sin refinar el modelo).
- Toda acción sobre turnos (crear, mover, cancelar, sobreturno, cambio de estado) escribe entrada de auditoría con actor, timestamp y valores anterior/nuevo.
- El token de paciente otorga capacidad solo sobre el `appointment_id` firmado; no es autenticación general.

## Rutas públicas

Sin autenticación (con rate-limit y protecciones específicas):

- `GET /b/:slug` — página de reserva online de la clínica (slug público).
- `GET /api/booking/:slug/availability` — disponibilidad (sin datos personales de otros pacientes: solo huecos libres).
- `POST /api/booking/:slug/appointments` — crear reserva.
- `GET /g/:token`, `PATCH /api/manage/:token` — gestión del turno por token (confirmar/cancelar/reprogramar).
- `POST /api/webhooks/whatsapp` — webhook de Meta (validado por firma `X-Hub-Signature-256`).
- `POST /api/auth/login`, `POST /api/auth/refresh` — autenticación del personal.

Todo lo demás exige JWT con rol autorizado. Los endpoints públicos de booking llevan rate-limit estricto (anti-enumeración de disponibilidad y anti-spam de reservas) y CAPTCHA/problemática de abuso registrada como decisión pendiente en `10_preguntas_abiertas.md`.
