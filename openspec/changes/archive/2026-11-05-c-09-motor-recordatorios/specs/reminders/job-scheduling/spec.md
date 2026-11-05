# Spec Delta — reminders/job-scheduling

## Purpose

Mantiene, para cada turno vigente, la secuencia de recordatorios persistida
(`reminder_job`) coherente con las mutaciones del turno: se crea al agendar, se
recalcula al reprogramar y se cancela al cancelar o confirmar, sin duplicar
mensajes y sin cruzar clínicas.

## ADDED Requirements

### Requirement: Secuencia de recordatorios al crear un turno

Al crear un turno vigente, por cualquier camino, el sistema SHALL insertar en la
misma transacción un job de alta de turno y un job por cada paso de
`clinic.reminder_steps`, con `scheduled_for = starts_at − offset_h` y el canal
del paso. El job de alta SHALL quedar programado para el instante de creación.

#### Scenario: Turno de recepción con pasos por defecto

- **WHEN** recepción crea un turno que empieza en 5 días en una clínica con pasos
  72/24/3 h por WhatsApp
- **THEN** existen cuatro jobs `scheduled` (alta, 72 h, 24 h, 3 h) con
  `scheduled_for` a 72, 24 y 3 horas antes de `starts_at` y el de alta al
  instante de creación

#### Scenario: Reserva online

- **WHEN** un paciente reserva online un turno que empieza en 5 días
- **THEN** se crean los mismos cuatro jobs en la misma transacción que el turno

#### Scenario: La creación falla

- **WHEN** la creación del turno responde `409 slot_taken`
- **THEN** no existe ningún `reminder_job` nuevo

### Requirement: Solo se programan pasos futuros

El sistema SHALL NOT crear un job cuyo `scheduled_for` no sea posterior al
instante de creación. Un turno creado cerca de su inicio SHALL recibir solo el
alta y los pasos que todavía quedan por delante.

#### Scenario: Turno creado 2 horas antes

- **WHEN** se crea un turno que empieza dentro de 2 horas
- **THEN** solo existe el job de alta y ningún job de 72 h, 24 h ni 3 h

#### Scenario: Turno creado 30 horas antes

- **WHEN** se crea un turno que empieza dentro de 30 horas
- **THEN** existen los jobs de alta, 24 h y 3 h y no el de 72 h

### Requirement: Idempotencia por turno, paso y canal

Para un mismo turno SHALL existir como máximo un job por combinación
`(appointment_id, step, channel)`, garantizado por la base. Reintentar la
programación del mismo turno SHALL NOT duplicar jobs.

#### Scenario: Programación repetida

- **WHEN** se ejecuta dos veces la programación del mismo turno
- **THEN** la cantidad de jobs es la misma que tras la primera ejecución

#### Scenario: La base rechaza el duplicado

- **WHEN** se intenta insertar a mano un segundo job con el mismo turno, paso y
  canal
- **THEN** la base lo rechaza por la restricción de unicidad

### Requirement: Reprogramar recalcula los jobs pendientes

Al reprogramar un turno, por recepción o por token, el sistema SHALL recalcular
en la misma transacción el `scheduled_for` de los jobs `scheduled`, crear los
pasos que vuelven a quedar en el futuro y cancelar los pendientes cuya hora ya
no sea futura. Los jobs ya enviados SHALL conservarse sin cambios.

#### Scenario: Turno movido una semana adelante

- **WHEN** un turno con jobs 72/24/3 h pendientes se reprograma 7 días más tarde
- **THEN** los tres jobs siguen `scheduled` con `scheduled_for` recalculado sobre
  el nuevo `starts_at`

#### Scenario: Turno movido a un horario más cercano

- **WHEN** un turno con el job de 72 h pendiente se reprograma a dentro de 10
  horas
- **THEN** el job de 72 h queda `cancelled` y el de 3 h queda `scheduled` con la
  nueva hora

#### Scenario: Paso ya enviado

- **WHEN** se reprograma un turno cuyo job de 72 h ya está `sent`
- **THEN** ese job no cambia y no se crea otro para el mismo paso y canal

### Requirement: Cancelar un turno cancela sus jobs pendientes

Cancelar un turno, por recepción, por bloqueo de agenda o por token, SHALL
marcar `cancelled` todos sus jobs `scheduled` en la misma transacción (RN-CX-03).
Un job `sending` SHALL resolverse antes de enviar, por la validación previa del
despacho.

#### Scenario: Cancelación por recepción

- **WHEN** recepción cancela un turno con tres jobs `scheduled`
- **THEN** los tres quedan `cancelled` y ninguno se envía

#### Scenario: Cancelación por bloqueo de agenda

- **WHEN** un bloqueo cancela un turno vigente en la misma request
- **THEN** sus jobs pendientes quedan `cancelled` en esa transacción

#### Scenario: Cancelación por token

- **WHEN** el paciente cancela con su link de gestión
- **THEN** los jobs pendientes quedan `cancelled` antes del commit de la mutación

### Requirement: Confirmar cancela solo los pasos que piden confirmar

Al confirmar un turno, por token, por respuesta o por recepción, el sistema
SHALL cancelar los jobs `scheduled` de los pasos que piden confirmación (los de
72 h y 24 h) y SHALL conservar los demás pasos. Un turno que nace `confirmed`
SHALL recibir todos sus pasos.

#### Scenario: Confirmación por token

- **WHEN** el paciente confirma con su link un turno con jobs 72/24/3 h pendientes
- **THEN** los de 72 h y 24 h quedan `cancelled` y el de 3 h sigue `scheduled`

#### Scenario: Turno de recepción

- **WHEN** recepción crea un turno, que nace `confirmed`
- **THEN** se crean los jobs de alta, 72 h, 24 h y 3 h

### Requirement: La invalidación es parte de la mutación

La programación, el recálculo y la cancelación de jobs SHALL ejecutarse dentro
de la transacción de la mutación del turno: si la mutación revierte, los jobs
vuelven a su estado anterior; si la programación falla, la mutación SHALL
revertir.

#### Scenario: Reversión conjunta

- **WHEN** una cancelación falla después de marcar sus jobs `cancelled`
- **THEN** el turno sigue vigente y sus jobs siguen `scheduled`

### Requirement: Aislamiento por clínica de los jobs

Toda tabla del motor SHALL llevar `clinic_id` obligatorio y referenciar al turno
y a la plantilla por clave compuesta con la clínica. Ninguna lectura o escritura
SHALL alcanzar jobs de otra clínica.

#### Scenario: Job con turno de otra clínica

- **WHEN** se intenta insertar un job con `clinic_id` de la clínica B y el
  `appointment_id` de un turno de la clínica A
- **THEN** la base lo rechaza por la clave foránea compuesta

#### Scenario: Cancelación acotada a la clínica

- **WHEN** se cancelan los jobs de un turno de la clínica A
- **THEN** los jobs de la clínica B no cambian
