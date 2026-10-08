# Decisiones y Supuestos

## Decisiones documentadas

### DD-01 — Stack: Python/FastAPI + SQLAlchemy + PostgreSQL + Redis + React+TS+Vite (Docker Compose)
**Decisión**: backend Python + FastAPI (async), ORM SQLAlchemy 2.x async, migraciones Alembic, PostgreSQL 15 como única base transaccional, Redis 7 para jobs/cola (reminder scheduler, WhatsApp queue/outbox, waiting-list jobs), frontend React + TypeScript + Vite, despliegue Docker / Docker Compose (`api`, `db`, `redis`, `worker`, `frontend`). Auth JWT access corto + refresh rotativo.
**Contexto**: mandato de stakeholder que reemplaza el stack anterior; fases posteriores exigen ARCA y Mercado Pago.
**Alternativas consideradas**: (a) Node.js/NestJS + React + Postgres — ecosistema Node con SDKs AR para MP/ARCA y TypeScript extremo a extremo, descartado por mandato; (b) Next.js fullstack + Prisma — velocidad inicial alta, pero acopla frontend y backend justo cuando el motor de recordatorios pedirá worker independiente; (c) Laravel/PHP — talento local abundante pero ORM menos apto para exclusion constraints.
**Justificación**: mandato de stakeholder + ecosistema Python (FastAPI async, SQLAlchemy 2.x, Alembic, talento disponible) + async nativo para scheduler/colas Redis + PostgreSQL con `tstzrange`/GiST para la invariante anti-solapamiento sin sincronización externa.
**Trade-offs aceptados**: equipo debe dominar SQL avanzado (constraints de exclusión vía DDL, locking con `SKIP LOCKED`, `AsyncSession`) — no es un CRUD generable por ORM ingenuo; SQLAlchemy no debe ocultar los constraints.
> Nota de supersesión: la decisión anterior (DD-01 original: Node.js/NestJS 10 + TypeScript, validación class-validator, ORM TypeORM/Prisma a decidir, jobs pg-boss vs BullMQ a decidir) queda **superseded** por mandato de stakeholder. Se conserva aquí como referencia histórica y no debe usarse para implementación.

### DD-02 — MVP agenda-first, clínica y cobros fuera
**Decisión**: v1.0 = solo agenda + booking + recordatorios + lista de espera + reportes mínimos. Odontograma, cobros, ARCA y obras sociales son fases posteriores explícitas.
**Contexto**: el Discovery pide el circuito completo, pero construirlo junto multiplica riesgo regulatorio (fiscal/sanitario) y superficie en un solo release.
**Alternativas consideradas**: (a) circuito completo en v1 — descartado: ARCA/OS exigen homologación y dominio regulatorio que frenarían la agenda meses; (b) agenda + cobros simples — descartado: cobrar sin facturar en AR genera deuda fiscal desde el día 1.
**Justificación**: la agenda es el prerrequisito de datos de todo lo demás; un piloto agenda-first valida ausentismo y adopción con riesgo bajo y da tracción comercial para financiar las fases reguladas.
**Trade-offs aceptados**: el MVP no factura ni cobra — el relato comercial debe vender "menos ausentismo y huecos llenos", no "sistema de gestión integral"; el modelo de datos debe dejar ganchos (patient_id, appointment_id estables) para clínica/cobros sin migración rompiente.

### DD-03 — RBAC simple de 4 roles, sin ABAC
**Decisión**: enum de rol (`admin`, `recepcion`, `odontologo`) + paciente por token. Sin permisos por registro salvo "odontólogo ve solo lo suyo".
**Contexto**: equipo chico, una clínica por tenant, velocidad de entrega prioritaria (R2-2).
**Alternativas consideradas**: permisos granulares por recurso/acción, ABAC por sillón/horario.
**Justificación**: el costo de un motor de permisos supera su beneficio con 3 roles internos; la única frontera sensible real (odontólogos entre sí) se cubre con un filtro de query.
**Trade-offs aceptados**: deuda técnica documentada — la fase multi-sucursal exigirá permisos granulares; el guard de roles debe diseñarse para evolucionar a políticas sin reescribir endpoints.

### DD-04 — Paciente sin cuenta (token capability)
**Decisión**: el paciente opera con links firmados por turno, no con usuario/contraseña.
**Contexto**: el paciente usa el sistema 2-4 veces al año; obligarlo a registrarse para confirmar un turno es fricción que mata la confirmación.
**Alternativas consideradas**: cuenta con DNI + OTP por WhatsApp; login social.
**Justificación**: maximiza tasa de confirmación (un toque), elimina recupero de contraseñas y reduce PII almacenada (sin passwords de pacientes que custodiar).
**Trade-offs aceptados**: seguridad delegada al secreto del link (TTL + rate-limit + rotación opcional); si un link se reenvía, quien lo tenga gestiona el turno — riesgo aceptado y comunicado, mitigable con confirmación de identidad por teléfono en recepción para casos sensibles.

### DD-05 — WhatsApp Cloud API oficial como único canal WhatsApp
**Decisión**: solo Meta Cloud API con plantillas aprobadas; prohibidos gateways no oficiales y números personales con automatización.
**Contexto**: el mercado AR abusa de bots sobre números personales (banneables) y de costos ocultos.
**Alternativas consideradas**: gateway no oficial (barato, baneable), solo SMS/email (barato, nadie lo lee).
**Justificación**: entregabilidad, trazabilidad de estados (enviado/entregado/leído) y cumplimiento de políticas Meta; el costo por mensaje se vuelve transparente y modelable en precio.
**Trade-offs aceptados**: dependencia de aprobación de plantillas y de pricing de Meta; se necesita proceso operativo de alta de plantillas por clínica.

### DD-06 — Jobs de recordatorio en Redis (worker async) + persistencia en Postgres
**Decisión**: scheduler/cola sobre Redis 7 con worker async (reminder scheduler, WhatsApp queue/outbox, waiting-list jobs); estado persistente en `reminder_job` Postgres con `FOR UPDATE SKIP LOCKED` + idempotencia `(appointment_id, step, channel)`.
**Contexto**: < 50 concurrentes por tenant; mandato de stack con Redis como componente estándar (servicio `worker` en Docker Compose).
**Alternativas consideradas**: jobs solo en Postgres sin Redis; cron en memoria del backend.
**Justificación**: cron en memoria pierde jobs al caer; Redis da cola/outbox, rate-limit y backoff con operación mínima vía Compose; Postgres sigue siendo la fuente de verdad del estado (los jobs sobreviven caídas del worker).
**Trade-offs aceptados**: un servicio más que operar (`redis`); la frontera `reminders/` + `worker/` aísla el backend de jobs para escalarlo sin tocar la API.

### DD-07 — Un tenant (DB) por clínica en fase 1
**Decisión**: single cloud deploy con una base por clínica; `clinic_id` como partición lógica preparando multi-tenant futuro.
**Contexto**: escala team (< 50 concurrentes), sin on-premise en fase 1.
**Alternativas consideradas**: multi-tenant real desde el día 1 (row-level security); on-premise por clínica.
**Justificación**: aislamiento de datos máximo (argumento comercial en salud), blast radius mínimo, y cero complejidad de RLS en v1; el costo (una DB gestionada por clínica) es lineal y predecible.
**Trade-offs aceptados**: costo infra por clínica y operación N-DBs; el código debe tratar `clinic_id` como obligatorio siempre para que la consolidación futura sea mecánica.

## Supuestos inferidos

### SU-01 — Ventana de cancelación de 24 h por defecto
**Supuesto**: 24 h es el default sano para la operatoria argentina relevada.
**Origen**: Q&A validado (ventana configurable) + práctica de competidores (DentalCore publica ventana configurable).
**Riesgo si es falso**: clínicas con prácticas largas (ortodoncia, implantes) necesitan 48/72 h y sufren cancelaciones tardías.
**Cómo validar**: preguntar en piloto por tipo de práctica; el parámetro ya es configurable por clínica.

### SU-02 — Tres pasos de recordatorio (72/24/3 h) por defecto
**Supuesto**: esa cadencia reduce ausentismo sin generar baja de opt-out por spam.
**Origen**: Q&A validado (jobs programados) + estándar de mercado (DentalCore usa 48/24 h; se agrega 72 h para reprogramación con margen).
**Riesgo si es falso**: fatiga de mensajes → opt-outs → el canal muere.
**Cómo validar**: medir opt-out por paso en piloto; ajustar cadencia por clínica si T-72 h genera ruido.

### SU-03 — El DNI no identifica pacientes en v1.0
**Supuesto**: match por teléfono E.164; el DNI es atributo opcional no único.
**Origen**: inferido — pedir DNI obligatorio frena la reserva online y los duplicados por DNI mal cargado son peores que por teléfono.
**Riesgo si es falso**: obras sociales y facturación futuras exigirán identidad fuerte; habrá que reconciliar pacientes.
**Cómo validar**: la fase OS definirá identidad (DNI/CUIL validado contra PUCO); el `patient_id` estable permite reconciliar sin romper agenda.

### SU-04 — Sillón como recurso independiente del profesional
**Supuesto**: modelar sillón separado aunque hoy haya consultorios de 1 sillón.
**Origen**: Q&A validado (multi-chair desde v1).
**Riesgo si es falso**: sobre-modelado para independientes (una tabla más en el alta).
**Cómo validar**: el seed crea "Sillón 1" por defecto; el alta de clínica unipersonal no pide sillones extra. Costo del supuesto ≈ 0.

### SU-05 — Delivery speed sobre perfección; deuda documentada aceptable
**Supuesto**: se prioriza llegar a piloto sobre pulir (permisos granulares, portal paciente, IA).
**Origen**: Q&A R2-2 validado por silencio (assumption stands).
**Riesgo si es falso**: si el piloto exige "grado médico" desde el día 1 (trazabilidad farmaciológica, firma), el MVP queda corto.
**Cómo validar**: el piloto es agenda pura en 1-2 clínicas amigas; cualquier pedido clínico/fiscal va a backlog de fase, no al MVP.

### SU-06 — Conectividad suficiente para SaaS puro en el piloto
**Supuesto**: las clínicas piloto tienen internet estable; no hay modo offline en v1.0.
**Origen**: Q&A (single cloud deploy, no on-premise) + Discovery (offline solo en Odontoly local-first).
**Riesgo si es falso**: cortes dejan a recepción sin agenda en hora pico.
**Cómo validar**: medir cortes en piloto; mitigación mínima v1: página de agenda del día imprimible/cacheada + cola de reintentos en frontend. Offline real es fase posterior.

### SU-07 — Costo WhatsApp trasladable/aceptado por la clínica
**Supuesto**: la clínica acepta costo variable por mensaje a cambio de menos ausentismo.
**Origen**: Q&A (WhatsApp Business API como infra asumida) + transparencia de Odonthia/AgendaPro con costos.
**Riesgo si es falso**: el unit economics del recordatorio no cierra y hay que capar pasos o pasar a email/SMS.
**Cómo validar**: registrar costo por mensaje desde el día 1 (RN-WA-05) y mostrarlo en el reporte; decidir pricing antes de escalar.
