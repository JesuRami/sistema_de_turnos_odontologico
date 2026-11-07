# reminders/delivery-timeline Specification

## Purpose
Da al personal de la clínica una vista operativa y de solo lectura del recorrido
de cada recordatorio de un turno —programado, enviado, entregado, leído, fallido,
saltado, cancelado o reenviado— sin exponer datos personales ni ids internos del
proveedor y sin cruzar clínicas.

## Requirements

### Requirement: Acceso al timeline por turno

`GET /api/appointments/{appointment_id}/reminders` SHALL devolver el timeline de
recordatorios del turno para admin, recepción y odontólogo, limitado a la clínica
del usuario. El odontólogo SHALL ver solo los turnos de su `professional_id`. Un
turno de otra clínica o ajeno al alcance SHALL responder `404 not_found`; sin
sesión, `401`.

#### Scenario: Recepción consulta un turno de su clínica

- **WHEN** recepción pide el timeline de un turno de su clínica con jobs de 72 h,
  24 h y 3 h
- **THEN** responde `200` con un elemento por paso y canal y sus eventos

#### Scenario: Turno de otra clínica

- **WHEN** un usuario de la clínica A pide el timeline de un turno de la clínica B
- **THEN** responde `404 not_found` y no revela ningún dato del turno

#### Scenario: Odontólogo consulta un turno ajeno

- **WHEN** un odontólogo pide el timeline de un turno de otro profesional de su
  clínica
- **THEN** responde `404 not_found`

#### Scenario: Odontólogo consulta su propio turno

- **WHEN** un odontólogo pide el timeline de un turno propio
- **THEN** responde `200` con los pasos y eventos, sin datos de contacto del
  paciente

### Requirement: Estado efectivo derivado de eventos

El estado de cada paso SHALL derivarse de los eventos del job y no solo de su
`status` mutable. Para el intento vigente SHALL aplicar esta precedencia: `read`
si hay un evento `read` posterior al último `sent`; si no, `delivered` si hay un
`delivered` posterior; si no, `failed` si hay un `failed` posterior; si no, el
estado actual del job. "Posterior" SHALL evaluarse contra el `sent` truncado al
segundo, porque Meta informa sus estados con segundos enteros.

#### Scenario: Secuencia normal

- **WHEN** un job fue `sent`, luego `delivered` y luego `read`
- **THEN** el paso muestra estado `read` y tres eventos en orden cronológico

#### Scenario: Entregado y fallido a la vez

- **WHEN** Meta informa `delivered` y también `failed` del mismo mensaje
- **THEN** el paso muestra estado `delivered`, con ambos eventos visibles

#### Scenario: Leído sin entregado

- **WHEN** llega un evento `read` sin un `delivered` previo
- **THEN** el paso muestra estado `read` y no inventa un evento `delivered`

#### Scenario: Fallo del último intento

- **WHEN** el último envío de un paso terminó en `failed` y no hubo un envío
  posterior exitoso
- **THEN** el paso muestra estado `failed` y el último código de error

#### Scenario: Entrega informada en el mismo segundo del envío

- **WHEN** Meta informa `delivered` con un `timestamp` del mismo segundo en que el
  motor registró el `sent` (unos milisegundos "antes")
- **THEN** el paso muestra estado `delivered`

### Requirement: Estado acotado a la última generación de envío

El estado efectivo SHALL considerar únicamente los eventos posteriores al último
reset de reenvío (la última fila `reminder_manual_resend` del job). Los eventos de
intentos anteriores y los propios reenvíos SHALL mostrarse en el historial como
`envío anterior` y SHALL NOT incidir en el estado efectivo vigente.

#### Scenario: Reenvío manual en curso

- **WHEN** recepción reenvió un paso que estaba `failed` y el worker todavía no
  lo envió
- **THEN** el paso muestra estado `scheduled` porque el `failed` del intento
  anterior es previo al reset; el `sent` anterior y el `manual_resend` aparecen
  marcados como envío anterior en el historial

### Requirement: Hito sintético de programación

El primer elemento de `events` SHALL ser un hito sintético `scheduled` (con la
hora de `available_at`) únicamente cuando el job se encuentre en estado
`scheduled` o `sending`; `scheduled` no es un evento persistido.

#### Scenario: Paso pendiente

- **WHEN** el paso de 3 h de un turno sigue `scheduled`
- **THEN** su primer evento es el hito `scheduled`

#### Scenario: Paso ya enviado

- **WHEN** el paso de 72 h ya está `sent`
- **THEN** sus eventos empiezan por el `sent`, sin hito `scheduled`

### Requirement: Detalle de eventos sin datos personales

Cada evento SHALL exponer solo un subconjunto seguro de su `payload`: intento,
tipo de mensaje, motivo, costo, destino lógico (`to`) y marca de reenvío manual
(`manual = true` en el `sent` resultante de una acción de recepción). La
respuesta SHALL NOT incluir `provider_message_id`, links de gestión, nombre,
teléfono, email ni DNI del paciente, y SHALL NOT registrar esos datos en logs.

#### Scenario: Evento con datos internos

- **WHEN** un evento `sent` tiene `provider_message_id` y `cost_micros` en su
  payload
- **THEN** la respuesta muestra `cost_micros` y no muestra el id del proveedor

#### Scenario: Nota de reenvío con un teléfono

- **WHEN** recepción intenta guardar una nota de reenvío que contiene un teléfono
- **THEN** la API rechaza la nota con `422 invalid_note` sin repetir el valor

### Requirement: Evento de reenvío manual en el historial

El evento `manual_resend` SHALL sintetizarse desde `reminder_manual_resend` por
`reminder_job_id`, con `occurred_at = created_at` y `detail = {"actor_role": ...}`.
La nota del reenvío SHALL NOT exponerse en el timeline.

#### Scenario: Reenvío con nota

- **WHEN** recepción reenvió un paso con una nota operativa
- **THEN** el timeline muestra el `manual_resend` con el rol del actor y no
  muestra la nota

### Requirement: Orden y lectura consistente

Los pasos SHALL devolverse en el orden `created`, `t_72h`, `t_24h`, `t_3h` y
luego cualquier otro paso con jobs; los canales, `whatsapp` antes que `email`; y
los eventos de cada job en orden cronológico ascendente. Dos lecturas sin
mutaciones intermedias SHALL devolver el mismo contenido.

#### Scenario: Orden de pasos y canales

- **WHEN** un turno tiene jobs de alta, 72 h, 24 h y 3 h por WhatsApp y email
- **THEN** la respuesta lista primero el alta y luego los pasos de mayor a menor
  anticipación, con WhatsApp antes que email

#### Scenario: Lectura repetida

- **WHEN** recepción consulta el mismo timeline dos veces sin que cambie nada
- **THEN** ambas respuestas tienen los mismos pasos, estados y eventos
