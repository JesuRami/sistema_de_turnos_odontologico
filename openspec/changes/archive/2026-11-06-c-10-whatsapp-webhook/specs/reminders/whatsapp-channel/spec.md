# Spec Delta — reminders/whatsapp-channel

## Purpose

Envía los mensajes de WhatsApp de la clínica por la Cloud API oficial de Meta,
con plantillas `es_AR` aprobadas, desde el número propio de la clínica o desde
un número compartido, sin exponer datos personales en logs ni errores.

## ADDED Requirements

### Requirement: Proveedor oficial de Meta

Con el proveedor de WhatsApp en `meta`, los recordatorios SHALL enviarse por la
Cloud API de Meta y por ningún otro gateway. El arranque SHALL fallar si falta el
token de acceso, el secreto de la app, el número por defecto o el token de
verificación, sin imprimir sus valores.

#### Scenario: Envío aceptado

- **WHEN** vence un job de WhatsApp de un paciente con opt-in y Meta acepta el
  mensaje
- **THEN** el job queda `sent` con el id de mensaje que devolvió Meta

#### Scenario: Configuración incompleta

- **WHEN** se arranca con el proveedor `meta` y sin token de acceso
- **THEN** el arranque falla con un error que nombra la variable faltante y no
  muestra ningún secreto

### Requirement: Número propio o compartido

Cada mensaje SHALL salir del número de WhatsApp configurado para la clínica del
turno; si la clínica no tiene uno, SHALL salir del número compartido por
defecto.

#### Scenario: Clínica con número propio

- **WHEN** la clínica A tiene número propio y vence un job suyo
- **THEN** el mensaje sale desde el número de la clínica A

#### Scenario: Clínica sin número propio

- **WHEN** la clínica B no tiene número propio y vence un job suyo
- **THEN** el mensaje sale desde el número compartido

### Requirement: Plantillas utilitarias en español argentino

Todo mensaje proactivo SHALL enviarse como la plantilla aprobada del paso
(`turno_creado_v1`, `recordatorio_72h_v1`, `recordatorio_24h_v1`,
`recordatorio_3h_v1`), en idioma `es_AR`, con nombre, clínica, profesional, fecha
y hora en formato argentino explícito y el link de gestión como parámetros.

#### Scenario: Parámetros de la plantilla

- **WHEN** se envía el recordatorio de 24 h de un turno del jueves 9/10 a las
  15:30 en la zona de la clínica
- **THEN** la plantilla `recordatorio_24h_v1` sale en `es_AR` con hora `15:30` y
  el link de gestión del turno

#### Scenario: Sin texto libre proactivo

- **WHEN** el paciente nunca escribió y vence cualquier paso
- **THEN** el mensaje sale como plantilla, nunca como texto libre

### Requirement: Botones de respuesta rápida

Las plantillas SHALL llevar botones de respuesta rápida que el webhook pueda
interpretar: confirmar (alta, 72 h y 24 h), cambiar (alta, 72 h y 24 h) y
cancelar (3 h).

#### Scenario: Botones del recordatorio de 24 h

- **WHEN** se envía el recordatorio de 24 h
- **THEN** incluye un botón de confirmar y uno de cambiar

#### Scenario: Botones del recordatorio de 3 h

- **WHEN** se envía el recordatorio de 3 h
- **THEN** incluye solo un botón de cancelar

### Requirement: Errores del proveedor clasificados

Un rechazo de Meta SHALL clasificarse como reintentable (límite de tasa, error
5xx, timeout, red, credenciales) o definitivo (destinatario inválido o fuera de
WhatsApp, plantilla inexistente o rechazada, parámetros inválidos). Un
definitivo SHALL fallar el job sin consumir la escalera de reintentos.

#### Scenario: Error transitorio

- **WHEN** Meta responde 503 al enviar
- **THEN** el job se reprograma con backoff

#### Scenario: Destinatario sin WhatsApp

- **WHEN** Meta informa que el número no es un usuario de WhatsApp
- **THEN** el job queda `failed` en ese intento y escala a email si corresponde

### Requirement: Sin datos personales en errores ni logs del canal

Los logs, `last_error` y los eventos del canal SHALL guardar solo códigos y
metadatos; SHALL NOT contener teléfono, nombre, email, link ni el cuerpo de la
respuesta de Meta.

#### Scenario: Rechazo con teléfono en el cuerpo

- **WHEN** Meta rechaza un envío con un mensaje de error que incluye el teléfono
- **THEN** el job y los logs registran solo un código estable, sin el teléfono

### Requirement: Credenciales fuera de los logs

El token de acceso de Meta SHALL viajar solo en el encabezado de autorización y
SHALL NOT aparecer en logs, errores ni URLs.

#### Scenario: Falla de autenticación

- **WHEN** Meta responde 401 por token vencido
- **THEN** el intento falla con un código de credenciales, el job se reprograma
  con backoff y ningún log contiene el token
