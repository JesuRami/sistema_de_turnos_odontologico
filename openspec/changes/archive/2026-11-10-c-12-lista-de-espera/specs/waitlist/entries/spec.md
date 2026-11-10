# Spec Delta — waitlist/entries

## Purpose

Registra quién espera un hueco, para qué profesional y en qué período y franja
le sirve, con una sola entrada activa por paciente y profesional, y deja la cola
consultable y operable por el personal de la clínica.

## ADDED Requirements

### Requirement: Contenido de una entrada

Una entrada SHALL tener paciente, profesional o "cualquiera", un período de
fechas locales `date_from`–`date_to` (inclusive) y, opcionales, una franja
horaria `time_from`–`time_to` y un conjunto de días de la semana. `date_from`
SHALL ser hoy o posterior, `date_to >= date_from`, y `date_to` SHALL caer dentro
del horizonte de reserva de la clínica. La franja SHALL cumplir `time_to >
time_from`; los días SHALL ser valores de 0 (lunes) a 6.

#### Scenario: Entrada mínima válida

- **WHEN** recepción anota a un paciente para "cualquiera" del 10/03 al 20/03
  sin franja ni días
- **THEN** responde `201` con la entrada en estado `waiting`

#### Scenario: Período invertido

- **WHEN** se anota con `date_from` posterior a `date_to`
- **THEN** responde `422 invalid_range` y no se crea nada

#### Scenario: Período fuera del horizonte

- **WHEN** el horizonte de la clínica es 60 días y `date_to` cae a 61 días de hoy
- **THEN** responde `422 range_too_large`

#### Scenario: Franja invertida

- **WHEN** se anota con `time_from=18:00` y `time_to=14:00`
- **THEN** responde `422 invalid_time_window`

#### Scenario: Fecha pasada

- **WHEN** `date_from` es ayer en la zona de la clínica
- **THEN** responde `422 invalid_range`

### Requirement: Una sola entrada activa por paciente y profesional

La base SHALL impedir dos entradas `waiting` u `offered` del mismo paciente para
el mismo profesional, tratando "cualquiera" como un valor más (RN-LE-01). Un
intento duplicado SHALL responder `409 already_waiting` con el id de la entrada
existente para el personal, y sin datos del paciente para el público.

#### Scenario: Duplicado para el mismo profesional

- **WHEN** un paciente tiene una entrada `waiting` para la Dra. Ficticia y
  recepción intenta anotarlo de nuevo para ella
- **THEN** responde `409 already_waiting` con el id de la existente

#### Scenario: Duplicado en "cualquiera"

- **WHEN** existe una entrada `offered` para "cualquiera" y se anota otra para
  "cualquiera" del mismo paciente
- **THEN** la base la rechaza y la API responde `409 already_waiting`

#### Scenario: Profesionales distintos

- **WHEN** el paciente tiene una entrada para "cualquiera" y se lo anota para un
  profesional concreto
- **THEN** responde `201`: son colas distintas

#### Scenario: Entrada cerrada no bloquea

- **WHEN** la entrada anterior está `converted`, `expired` o `withdrawn`
- **THEN** se puede crear una nueva para el mismo profesional

#### Scenario: Carrera de dos altas

- **WHEN** dos requests concurrentes anotan al mismo paciente para el mismo
  profesional
- **THEN** una responde `201` y la otra `409 already_waiting`, con una sola fila

### Requirement: Alta desde recepción

Admin y recepción SHALL anotar a un paciente existente y no archivado de su
clínica, con una nota operativa opcional de hasta 200 caracteres que SHALL NOT
contener DNI, teléfono ni email. El profesional, si se indica, SHALL ser de la
clínica y estar activo.

#### Scenario: Paciente de otra clínica

- **WHEN** recepción anota un `patient_id` de otra clínica
- **THEN** responde `422 invalid_patient`

#### Scenario: Nota con teléfono

- **WHEN** la nota incluye un número de teléfono
- **THEN** responde `422 invalid_note` y no se crea la entrada

#### Scenario: Profesional inactivo

- **WHEN** se anota para un profesional desactivado
- **THEN** responde `409 resource_inactive`

#### Scenario: Odontólogo no anota

- **WHEN** un odontólogo intenta crear una entrada
- **THEN** responde `403 forbidden_role`

### Requirement: Anotación pública

`POST /api/booking/{slug}/waiting-list` SHALL anotar sin sesión con nombre, al
menos un contacto válido, la elección explícita de opt-in de WhatsApp si hay
teléfono, la aceptación de la política de privacidad, profesional reservable o
"cualquiera" y las preferencias. SHALL reutilizar el paciente con el mismo
teléfono y nombre normalizados o crear uno, como la reserva online.

#### Scenario: Anotación pública exitosa

- **WHEN** un visitante sin cuenta se anota con nombre, teléfono, opt-in de
  WhatsApp y un período válido
- **THEN** responde `201` con profesional, período y franja, sin ids internos del
  paciente, y la entrada queda `waiting` con origen `online`

#### Scenario: Sin contacto

- **WHEN** se anota solo con el nombre
- **THEN** responde `422` y no se crea paciente ni entrada

#### Scenario: Paciente existente reutilizado

- **WHEN** el teléfono y el nombre coinciden con un paciente de la clínica
- **THEN** la entrada usa ese paciente y no se crea otra ficha

#### Scenario: Opt-in registrado

- **WHEN** el visitante marca el opt-in de WhatsApp
- **THEN** se registra el consentimiento con fuente `booking` en la misma
  transacción que la entrada

#### Scenario: Slug inexistente o reserva deshabilitada

- **WHEN** se anota en un slug que no existe o con la reserva deshabilitada
- **THEN** responde `404 booking_not_found` con el mismo cuerpo que la reserva

### Requirement: Protección de la anotación pública

La anotación pública SHALL limitarse por IP y por slug con cupos propios, SHALL
responder `429 rate_limited` con `Retry-After` al excederse y `503
booking_unavailable` si el almacenamiento del cupo no está disponible, y SHALL
pasar por el mismo punto de verificación anti-bot que la reserva.

#### Scenario: Cupo por IP excedido

- **WHEN** una IP supera el cupo de anotaciones por hora
- **THEN** responde `429 rate_limited` con `Retry-After` y no crea nada

#### Scenario: Redis caído

- **WHEN** el almacenamiento del rate-limit no responde
- **THEN** responde `503 booking_unavailable` y no crea nada

### Requirement: Edición y retiro de una entrada

Admin y recepción SHALL editar profesional, preferencias y nota de una entrada
`waiting` con las mismas validaciones del alta, y SHALL retirarla (`withdrawn`)
mientras esté `waiting` u `offered`. Retirar una entrada `offered` SHALL cerrar
su oferta pendiente. Una entrada cerrada SHALL NOT editarse.

#### Scenario: Editar la franja

- **WHEN** recepción cambia la franja de una entrada `waiting`
- **THEN** responde `200` y se registra un evento con los valores anterior y nuevo

#### Scenario: Editar una entrada ofrecida

- **WHEN** recepción edita una entrada `offered`
- **THEN** responde `409 entry_offered` y no cambia

#### Scenario: Retiro con oferta pendiente

- **WHEN** recepción retira una entrada `offered`
- **THEN** la entrada queda `withdrawn` y su oferta pendiente queda `cancelled`

#### Scenario: Retirar una entrada convertida

- **WHEN** se retira una entrada `converted`
- **THEN** responde `409 entry_closed`

### Requirement: Vencimiento por período

Una entrada `waiting` cuyo `date_to` ya pasó en la zona de la clínica SHALL
quedar `expired` con motivo `range_elapsed` en el siguiente tick del worker, sin
mensaje al paciente.

#### Scenario: Período terminado

- **WHEN** el `date_to` de una entrada `waiting` fue ayer y corre el tick
- **THEN** la entrada queda `expired` con motivo `range_elapsed` y su evento

#### Scenario: Último día del período

- **WHEN** hoy es el `date_to` de la entrada y corre el tick
- **THEN** la entrada sigue `waiting`

### Requirement: Prioridad como excepción a FIFO

Admin y recepción SHALL marcar una entrada `waiting` u `offered` como prioritaria
con un motivo obligatorio (10 a 200 caracteres, sin DNI, teléfono ni email) y
SHALL poder quitar la prioridad. La marca y su retiro SHALL quedar auditados con
actor y motivo. Las entradas prioritarias SHALL ordenarse antes que las demás.

#### Scenario: Priorizar con motivo

- **WHEN** recepción prioriza una entrada con motivo "urgencia por dolor"
- **THEN** la entrada queda prioritaria y el evento registra actor y motivo

#### Scenario: Priorizar sin motivo

- **WHEN** se prioriza sin motivo
- **THEN** responde `422 priority_reason_required` y la entrada no cambia

#### Scenario: Odontólogo no prioriza

- **WHEN** un odontólogo intenta priorizar
- **THEN** responde `403 forbidden_role`

### Requirement: Cola consultable

`GET /api/waiting-list` SHALL listar las entradas de la clínica filtrables por
estado (default `waiting` y `offered`), profesional y período (entradas cuyo
período intersecta el rango), ordenadas por prioridad y luego por antigüedad,
paginadas por cursor con `limit` de 1 a 200. Cada entrada SHALL incluir su
oferta pendiente si la tiene.

#### Scenario: Orden de la cola

- **WHEN** hay dos entradas comunes de distinto alta y una prioritaria más nueva
- **THEN** la prioritaria aparece primera y las comunes por antigüedad

#### Scenario: Filtro por profesional

- **WHEN** se filtra por la Dra. Ficticia
- **THEN** aparecen sus entradas y las de "cualquiera"

#### Scenario: Paginación estable

- **WHEN** se piden dos páginas de 50 con el cursor devuelto
- **THEN** no hay repetidos ni faltantes respecto de una sola página de 100

### Requirement: Alcance por rol de la cola

Admin y recepción SHALL ver todas las entradas con nombre, teléfono y email del
paciente. El odontólogo SHALL ver solo las entradas de su profesional y de
"cualquiera", con nombre del paciente y sin teléfono, email ni notas, y SHALL NOT
ejecutar ninguna acción sobre la lista.

#### Scenario: Odontólogo lee la cola

- **WHEN** un odontólogo lista la cola
- **THEN** ve sus entradas y las de "cualquiera" sin datos de contacto

#### Scenario: Sin sesión

- **WHEN** se lista la cola sin sesión
- **THEN** responde `401`

### Requirement: Aislamiento por clínica de la lista

Ninguna operación de la lista SHALL leer ni modificar entradas, ofertas o
eventos de otra clínica. Pedir una entrada ajena por id SHALL responder `404
not_found`, y la base SHALL rechazar una entrada cuyo paciente o profesional sea
de otra clínica.

#### Scenario: Entrada de otra clínica

- **WHEN** recepción de la clínica A pide o retira una entrada de la clínica B
- **THEN** responde `404 not_found` y nada cambia

#### Scenario: FK cruzada rechazada por la base

- **WHEN** se inserta directamente una entrada con `clinic_id` A y paciente de B
- **THEN** la base la rechaza por FK compuesta

### Requirement: Auditoría de la entrada

Cada alta, edición, prioridad, retiro, vencimiento y conversión de una entrada
SHALL escribir un evento append-only en la misma transacción, con tipo, actor
(usuario, paciente por token o sistema) y valores sin PII. La base SHALL rechazar
`UPDATE` y `DELETE` de esos eventos. `GET /api/waiting-list/{id}/events` SHALL
devolverlos en orden a admin y recepción.

#### Scenario: Evento en la misma transacción

- **WHEN** falla la escritura del evento de un retiro
- **THEN** el retiro entero revierte y la entrada sigue como estaba

#### Scenario: Eventos inmutables

- **WHEN** se intenta `UPDATE` sobre un evento de la lista
- **THEN** la base lo rechaza

#### Scenario: Sin PII en eventos

- **WHEN** se lee el payload de cualquier evento de la lista
- **THEN** no contiene nombre, teléfono, email ni DNI del paciente
