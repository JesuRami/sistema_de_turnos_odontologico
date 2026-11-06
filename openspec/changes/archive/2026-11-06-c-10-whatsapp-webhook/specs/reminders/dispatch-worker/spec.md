# Spec Delta — reminders/dispatch-worker

## MODIFIED Requirements

### Requirement: Trazabilidad y costo por clínica y paso

Cada envío exitoso SHALL guardar `provider_message_id`, el instante de envío y el
costo estimado del canal, y SHALL registrar un evento en `delivery_event`,
append-only, por cada intento, envío, salto, cancelación, escalado y estado
informado por el proveedor (`delivered`, `read`, `failed`). El costo SHALL poder
agregarse por clínica y paso.

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

#### Scenario: Estado informado por el proveedor

- **WHEN** Meta informa que un mensaje enviado fue entregado
- **THEN** existe un evento `delivered` asociado al job de ese mensaje

### Requirement: Canales detrás de un puerto y sin envíos falsos

Los envíos SHALL pasar por un puerto por canal. Mientras el proveedor del canal
esté deshabilitado el worker SHALL NOT reclamar sus jobs ni marcarlos como
enviados. WhatsApp SHALL admitir los proveedores `disabled`, `fake` y `meta`.

#### Scenario: WhatsApp deshabilitado

- **WHEN** el proveedor de WhatsApp está deshabilitado y vence un job de WhatsApp
- **THEN** el job sigue `scheduled` y no hay evento de envío

#### Scenario: Sin PII en logs

- **WHEN** el worker envía y falla un recordatorio
- **THEN** ni los logs ni `last_error` ni los eventos contienen nombre, teléfono,
  email ni el link del paciente

#### Scenario: Proveedor real

- **WHEN** el proveedor de WhatsApp es `meta` y vence un job de WhatsApp válido
- **THEN** el mensaje se envía por la Cloud API de Meta

### Requirement: Ventana de 24 h de Meta

El sistema SHALL usar plantilla aprobada para todo recordatorio proactivo y SHALL
permitir un seguimiento libre solo dentro de las 24 h posteriores al último
mensaje entrante registrado del paciente en esa clínica.

#### Scenario: Sin mensaje entrante

- **WHEN** el paciente nunca escribió a la clínica
- **THEN** el recordatorio se envía como plantilla

#### Scenario: Dentro de la ventana

- **WHEN** el paciente escribió hace 2 horas
- **THEN** la elección habilita el seguimiento libre para esa respuesta

#### Scenario: Recordatorio con ventana abierta

- **WHEN** el paciente escribió hace 2 horas y vence su recordatorio de 3 h
- **THEN** el recordatorio igual se envía como plantilla

#### Scenario: Ventana vencida

- **WHEN** el último mensaje entrante del paciente fue hace 25 horas
- **THEN** la elección no habilita el seguimiento libre
