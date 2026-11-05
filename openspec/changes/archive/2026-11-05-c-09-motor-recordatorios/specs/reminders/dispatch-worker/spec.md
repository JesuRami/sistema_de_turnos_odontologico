# Spec Delta — reminders/dispatch-worker

## Purpose

Envía los recordatorios vencidos desde un worker persistente: reclama jobs sin
duplicarlos entre ticks ni réplicas, valida cada uno antes de enviar, reintenta
con backoff, escala a email y deja trazabilidad y costo por clínica y paso.

## ADDED Requirements

### Requirement: Reclamo de jobs sin duplicados

Cada tick, de 60 s, SHALL reclamar hasta 100 jobs `scheduled` vencidos con bloqueo
de fila que saltea los ya tomados, y marcarlos `sending` con su instante de
reclamo. Dos ticks simultáneos o dos réplicas SHALL NOT reclamar ni enviar el
mismo job.

#### Scenario: Doble tick

- **WHEN** dos ticks corren a la vez sobre 10 jobs vencidos
- **THEN** cada job se envía exactamente una vez y no queda ninguno `sending`

#### Scenario: Más de 100 vencidos

- **WHEN** hay 250 jobs vencidos
- **THEN** el tick los procesa en lotes de hasta 100 hasta vaciarlos o agotar su
  presupuesto de tiempo, y los restantes siguen `scheduled`

#### Scenario: Job aún no vencido

- **WHEN** un job tiene `scheduled_for` en el futuro
- **THEN** el tick no lo reclama

### Requirement: Los jobs sobreviven a la caída del worker

El estado de la cola SHALL vivir en Postgres. Un job `sending` cuyo reclamo
superó el plazo del lease SHALL volver a `scheduled` sin pérdida, y los jobs
vencidos durante la caída SHALL procesarse al volver el worker.

#### Scenario: Worker caído y reiniciado

- **WHEN** el worker está detenido mientras vencen tres jobs y luego arranca
- **THEN** el primer tick envía los jobs cuyo turno no empezó y salta los demás

#### Scenario: Lease vencido

- **WHEN** un job quedó `sending` más allá del plazo de lease por un worker caído
- **THEN** vuelve a `scheduled` y se reclama en el tick siguiente

### Requirement: Validación previa al envío

Antes de enviar, el sistema SHALL verificar bajo bloqueo que el turno siga
vigente, que no haya empezado, que `starts_at` coincida con el que se usó para
programar el job, que el paciente tenga consentimiento vigente del canal y que
exista una plantilla activa del paso y canal. Si alguna falla, SHALL NOT enviar.

#### Scenario: Turno cancelado

- **WHEN** vence un job de un turno `cancelled`
- **THEN** el job queda `cancelled` y no se envía nada

#### Scenario: Sin consentimiento de WhatsApp

- **WHEN** vence un job de WhatsApp y el paciente no tiene opt-in vigente
- **THEN** el job queda `skipped` con motivo `no_consent` y no se envía nada

#### Scenario: Plantilla inactiva

- **WHEN** vence un job y su plantilla está inactiva
- **THEN** el job queda `failed` con motivo `template_inactive` y se aplica el
  escalado

#### Scenario: Horario cambiado

- **WHEN** vence un job cuyo turno fue movido y el job no se recalculó
- **THEN** el sistema recalcula la secuencia del turno y no envía con la hora vieja

#### Scenario: Canal sin destinatario

- **WHEN** vence un job de email y el paciente no tiene dirección cargada
- **THEN** el job queda `skipped` con motivo `no_recipient` y no se envía nada

#### Scenario: Turno cancelado entre el reclamo y el envío

- **WHEN** el turno se cancela después de reclamar el job y antes de enviarlo
- **THEN** el job queda `cancelled` y no se envía nada

### Requirement: Nunca se recuerda un turno ya iniciado

Un job vencido de un turno cuyo `starts_at` ya pasó SHALL pasar a `skipped` con
motivo `appointment_started`, nunca a `sent`.

#### Scenario: Recordatorio tardío

- **WHEN** el worker vuelve de una caída y un job de 3 h vence 10 minutos después
  de iniciado el turno
- **THEN** el job queda `skipped` y no se envía nada

### Requirement: Opt-out a mitad de la secuencia

Si el paciente se da de baja del canal con jobs pendientes, el sistema SHALL
dejar esos jobs `skipped` con motivo `no_consent` sin enviarlos.

#### Scenario: Baja entre el aviso de 72 h y el de 24 h

- **WHEN** el job de 72 h se envió y luego el paciente queda con `opt_out` de
  WhatsApp
- **THEN** los jobs de 24 h y 3 h quedan `skipped` y el de 72 h conserva `sent`

### Requirement: Reintentos con backoff y escalado a email

Un envío con error transitorio SHALL reintentarse con backoff creciente (5 min,
luego 30 min); el tercer fallo consecutivo SHALL dejar el job `failed`. Un error
no reintentable SHALL fallar de inmediato.
Al fallar un job de WhatsApp, si el paciente tiene email y no se dio de baja de
ese canal, el sistema SHALL crear el job de email del mismo paso.

#### Scenario: Éxito en el segundo intento

- **WHEN** el primer envío falla con error transitorio y el segundo tiene éxito
- **THEN** el job queda `sent` con `attempts = 2`

#### Scenario: Tres fallos escalan a email

- **WHEN** un job de WhatsApp falla tres veces y el paciente tiene email
- **THEN** queda `failed` y existe un job de email `scheduled` del mismo turno y
  paso

#### Scenario: Sin email

- **WHEN** un job de WhatsApp falla tres veces y el paciente no tiene email
- **THEN** queda `failed` y no se crea ningún job de email

#### Scenario: Error no reintentable

- **WHEN** el proveedor rechaza el destinatario por inválido
- **THEN** el job queda `failed` sin esperar los reintentos y se aplica el
  escalado

### Requirement: Trazabilidad y costo por clínica y paso

Cada envío exitoso SHALL guardar `provider_message_id`, el instante de envío y el
costo estimado del canal, y SHALL registrar un evento en `delivery_event`,
append-only, por cada intento, envío, salto, cancelación y escalado. El costo
SHALL poder agregarse por clínica y paso.

#### Scenario: Envío exitoso

- **WHEN** un job de WhatsApp se envía
- **THEN** el job guarda el id del proveedor, queda `sent` y existe un evento de
  envío asociado

#### Scenario: Costo agregable

- **WHEN** una clínica envió dos jobs de 24 h y uno de 3 h
- **THEN** el costo sumado por paso de esa clínica refleja 2 y 1 envíos y no
  incluye los de otra clínica

#### Scenario: Eventos inmutables

- **WHEN** se intenta modificar o borrar una fila de `delivery_event`
- **THEN** la base lo rechaza

### Requirement: Canales detrás de un puerto y sin envíos falsos

Los envíos SHALL pasar por un puerto por canal. Mientras el proveedor del canal
esté deshabilitado el worker SHALL NOT reclamar sus jobs ni marcarlos como
enviados.

#### Scenario: WhatsApp deshabilitado

- **WHEN** el proveedor de WhatsApp está deshabilitado y vence un job de WhatsApp
- **THEN** el job sigue `scheduled` y no hay evento de envío

#### Scenario: Sin PII en logs

- **WHEN** el worker envía y falla un recordatorio
- **THEN** ni los logs ni `last_error` ni los eventos contienen nombre, teléfono,
  email ni el link del paciente

### Requirement: Contenido del mensaje

El mensaje SHALL renderizarse con la plantilla del paso: nombre del paciente,
clínica, profesional, fecha y hora en formato argentino y zona de la clínica
(por ejemplo “jueves 9/10, 15:30”) y el link de gestión del turno.

#### Scenario: Fecha en la zona de la clínica

- **WHEN** se renderiza un turno a las 18:30 UTC de la clínica con zona
  `America/Argentina/Buenos_Aires`
- **THEN** la hora del mensaje es 15:30

#### Scenario: Link utilizable

- **WHEN** el paciente abre el link del mensaje
- **THEN** la gestión por token resuelve su turno

### Requirement: Ventana de 24 h de Meta

El sistema SHALL usar plantilla aprobada para todo recordatorio proactivo y SHALL
permitir un seguimiento libre solo dentro de las 24 h posteriores a un mensaje
entrante del paciente.

#### Scenario: Sin mensaje entrante

- **WHEN** el paciente nunca escribió a la clínica
- **THEN** el recordatorio se envía como plantilla

#### Scenario: Dentro de la ventana

- **WHEN** el paciente escribió hace 2 horas
- **THEN** la elección habilita el seguimiento libre para esa respuesta
